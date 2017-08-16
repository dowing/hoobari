# --------- import modules ------------
# external
import os, sys
import sqlite3
import vcf
from numpy import repeat as nprepeat
import pandas as pd
import matplotlib
import numpy as np
import seaborn as sns
from multiprocessing import Pool, cpu_count
from functools import partial
import re

# project's
from json_commands import *
from pkl_commands import *
import parse_gt
from stderr import *
import vcfuid



# --------- functions ----------

def get_fetal_and_shared_lengths(db_path):

	con = sqlite3.connect(db_path, isolation_level = None)

	try:
		shared_df = pd.read_sql_query("select chromosome, qname, length from variants where for_ff=2 and chromosome not in ('X', 'Y');", con).drop_duplicates()
		fetal_df = pd.read_sql_query("select chromosome, qname, length from variants where for_ff=1 and chromosome not in ('X', 'Y');", con).drop_duplicates()
	except:
		print(db_path)
		sys.exit(1)

	shared_lengths, fetal_lengths = list(shared_df['length']), list(fetal_df['length'])

	con.close()

	return (shared_lengths, fetal_lengths)

def create_length_distributions(db_path, db_prefix = False):
	'''
	variant name - form of chr:position_ref/alt
	fetal - choose either the fetal allele is suppose to be the ref (if mother = 1/1 and father = 0/0)
	or the alt (if mother = 0/0 and father = 1/1)
	'''	
	

	if cpu_count() > 1:
		pool = Pool(cpu_count() - 1)
	else:
		pool = Pool(1)
	
	db_path = os.path.abspath(db_path)
	if db_prefix:
		db_file_regex = re.compile(db_prefix + r'.*\.db')
		db_files_loc = os.path.dirname(db_path)
		db_files = [os.path.join(db_files_loc, file) for file in os.listdir(db_files_loc) if re.match(db_file_regex, file)]
	else:
		db_files = [db_path]

	pooled_results = pool.map(get_fetal_and_shared_lengths, db_files)
	pool.close()
	pool.join()

	shared_lengths = [l for tup in pooled_results for l in tup[0]]
	fetal_lengths = [l for tup in pooled_results for l in tup[1]]

	return (shared_lengths, fetal_lengths)

def generate_length_distributions_plot(shared_lengths_list, fetal_lengths_list):
	#show length distributions plot
	shared_plot_data = pd.Series(shared_lengths_list)
	fetal_plot_data = pd.Series(fetal_lengths_list)
	shared_plot_data = shared_plot_data[shared_plot_data < 500]#.plot.kde()
	fetal_plot_data = fetal_plot_data[fetal_plot_data < 500]#.plot.kde()
	sns.kdeplot(np.array(shared_plot_data), bw=0.5)
	sns.kdeplot(np.array(fetal_plot_data), bw=0.5)
	matplotlib.use('Agg')
	matplotlib.pyplot.xlim(0, 500)
	matplotlib.pyplot.savefig('length_distributions.png')
	
def create_fetal_fraction_per_length_df(shared_lengths_list, fetal_lengths_list, window = 3, max = 500, plot = False):
	'''
	make a dictionary that shows the fetal fraction at each fragment length
	'''

	printerr('making a dictionary that shows the fetal fraction at each fragment length:')

	# generate length distributions plot
	if plot:
		generate_length_distributions_plot(shared_lengths_list, fetal_lengths_list)

	# generate fetal fraction per fragment length (window) table
	bins = range(0,max,window)
	
	fetal_pd_cut = pd.cut(fetal_lengths_list, bins, include_lowest = True)
	shared_pd_cut = pd.cut(shared_lengths_list, bins, include_lowest = True)

	
	fetal_binned = pd.value_counts(fetal_pd_cut, sort = False).to_frame().values.tolist()
	shared_binned = pd.value_counts(shared_pd_cut, sort = False).to_frame().values.tolist()
	
	
	fetal_fraction_per_length_df = pd.Series(index = range(0, bins[-1] + 1, 1))

	binned_list_indices = [0] + list(nprepeat(range(len(fetal_binned)), window))

	for i in range(len(fetal_fraction_per_length_df)):
		idx_in_binned = binned_list_indices[i]
		fetal = fetal_binned[idx_in_binned][0]
		shared = shared_binned[idx_in_binned][0]
		if fetal > 5 and shared > 5:
			fetal_fraction_per_length_df[i] = (2 * fetal) / (shared + fetal)
		else:
			fetal_fraction_per_length_df[i] = fetal_fraction_per_length_df[i-1]
	
	return fetal_fraction_per_length_df

def calculate_total_fetal_fraction(shared_lengths_list, fetal_lengths_list):
	total_fetal_fraction = (2 * len(fetal_lengths_list)) / (len(shared_lengths_list) + len(fetal_lengths_list))
	printerr('Total fetal fraction: ', total_fetal_fraction)
	return total_fetal_fraction

def calculate_err_rate():
	err = 0.003
	return err
