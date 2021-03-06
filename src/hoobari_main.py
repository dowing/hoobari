# --------- import modules ------------
# external
import re
import os
import sys
import subprocess
import requests
import vcf, vcf.utils
import numpy as np
import pandas as pd
from collections import OrderedDict
import pickle
import time
import pysam
# project's
import parse_gt
from stderr import *
import vcfuid
import position
import vcf_out
import preprocessing
from arguments import args
from db import Variants


def split_region(regionstr):
	region_split = re.split(':|-', regionstr)
	chrom = region_split[0]
	start = int(region_split[1]) if len(region_split) > 1 else None
	end = int(region_split[2]) if len(region_split) > 2 else None
	return(chrom, start, end)

# connect to the database that was created during the first analysis of the cfDNA sample
if args.region:
	args.db = args.tmp_dir
	vardb = Variants(os.path.join(args.tmp_dir, str(args.region) + '.db'), probe=False)
else:
	vardb = Variants(args.db, probe=False)

# pre-processing
# calculate the total fetal fraction and a table of fetal-fraction per fragment size
# TODO: note that the error rate isn't actually used in the model yet
err_rate, total_fetal_fraction, fetal_fractions_df = preprocessing.run_full_preprocessing(	args.db,
												args.fetal_sample_name,
												float(args.fetal_fraction),
												args.use_prior_ff_dist,
												args.cores,
												window = args.window,
												max_len = 500,
												plot = args.plot_lengths,
												qnames = args.qnames,
												region = args.region)

# with open('preprocessing_info.txt', 'w') as pp_info:
# 	print('total_fetal_fraction', total_fetal_fraction, file = pp_info)
# 	print('err_rate', err_rate, file = pp_info)
# 	fetal_fractions_df.to_csv(pp_info, sep = '\t')


bam_file_reader = pysam.AlignmentFile(os.path.join(args.cfdna_bam), 'rb')

# create vcf files iterators
try:
	cfdna_reader = vcf.Reader(filename = args.cfdna_vcf)
	parents_reader = vcf.Reader(filename = args.parents_vcf)
except:
	sys.exit('warning! could not create iterator for the vcf. \
	probably the input file does not contain any variants in the region.')

# print header of output vcf file
input_command = ' '.join(sys.argv)
vcf_out.make_header(	cfdna_reader,
			parents_reader,
			input_command,
			args.fetal_sample_name,
			vcf_out.reserved_formats,
			output_path = args.vcf_output)

# fetch region, if a region was specified
if args.region:
	chrom, start, end = split_region(args.region)
	try:
		cfdna_reader = cfdna_reader.fetch(chrom, start, end)
		parents_reader = parents_reader.fetch(chrom, start, end)
	except ValueError as e:
		errmessage = e.args[0]
		if 'could not create iterator for region' in errmessage:
			sys.exit('warning! ' + errmessage + ', probably the input file does not contain any variants in the region.')


# get sample of cfdna from its vcf file, and of the parents from the input arguments
cfdna_id = cfdna_reader.samples[0]
mother_id, father_id = vardb.get_samples()	

# processing positions
# iterate on both vcf files and return a tuple for each position, that contains its record from each vcf file.
# if there is no vcf record for a certain position in one of the files, a None will appear in the tuple instead.
co_reader = vcf.utils.walk_together(cfdna_reader, parents_reader)
for tup in co_reader:
	# reset prediction and QUAL
	prediction = qual = None
	rec_info = []

	cfdna_rec, parents_rec = tup

	printverbose('parents_rec: ', parents_rec)
	printverbose('cfdna_rec: ', cfdna_rec)

	if not parents_rec:
		vcf_out.unsupported_position(cfdna_rec, out_path = args.vcf_output)
	else: # if parental and cfdna record

		# fetch parental genotypes
		maternal_gt = parse_gt.str_to_int(parents_rec.genotype(mother_id).data.GT)
		paternal_gt = parse_gt.str_to_int(parents_rec.genotype(father_id).data.GT)
		printverbose(maternal_gt, paternal_gt)

		
		if not cfdna_rec:
			cfdna_rec = parents_rec
			qual = 0
			cfdna_geno_sample_dic = '.'
		elif maternal_gt not in (0,1,2):
			qual = 0
			cfdna_geno_sample_dic = '.'
		else:
			# for now, only positions where the mother is 0/0, 0/1 or 1/1 are supported
			if maternal_gt in (0,1,2):
			
				# calculate priors for the position
				priors = position.calculate_priors(maternal_gt, paternal_gt)
				
				# calculate likelihoods for the position
				likelihoods = position.calculate_likelihoods(	cfdna_rec,
										bam_file_reader,
										maternal_gt,
										total_fetal_fraction,
										fetal_fractions_df,
										err_rate,
										vardb,
										args.model,
										args.max_used_reads)

				# calculate posteriors for the position
				posteriors, prediction, qual = position.calculate_posteriors(priors, likelihoods)


				## process the output entry

				# create normalized likelihoods for the output vcf
				normalized_likelihoods = position.likelihoods_to_phred_scale(likelihoods)

				# fetal information for the sample and FORMAT fields
				cfdna_geno_sample_dic = vcf_out.rec_sample_to_string(cfdna_rec, cfdna_id)
				if cfdna_geno_sample_dic != '.':
					cfdna_geno_sample_dic['GT'] = parse_gt.int_to_str(prediction)
					cfdna_geno_sample_dic['GL'] = (','.join(str(round(p,2)) for p in list(normalized_likelihoods)))
					cfdna_geno_sample_dic['PG'] = (','.join(str(round(p,5)) for p in list(priors)))
					cfdna_geno_sample_dic['PP'] = (','.join(str(round(p,5)) for p in list(posteriors)))

				rec_info.append(vcf_out.info_to_string(cfdna_rec.INFO))

		# for each parent, for all the data in its sample, create an instance that will be printed in the output INFO
		rec_info.append(vcf_out.parents_gt_to_info(mother_id, father_id, parents_rec))
		
		parental_info_for_info = vcf_out.info_to_string(parents_rec.INFO)
		parental_info_for_info = 'P' + parental_info_for_info.replace(';',';P')
		rec_info.append(parental_info_for_info)
		
		rec_info = ';'.join(rec_info)

		rec_info = rec_info.replace('None', '.')

		# write var out (to file passed with -v or to output)
		vcf_out.print_var(cfdna_rec, qual, rec_info, cfdna_geno_sample_dic, out_path = args.vcf_output)
	
printerr('completed successfully')
