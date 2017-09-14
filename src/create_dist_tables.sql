create table if not exists fetal_lengths(
    `length` int NOT NULL,
    `count`  int NOT NULL DEFAULT '0',
    PRIMARY KEY (`length`)
);

create table if not exists shared_lengths(
    `length` int NOT NULL,
    `count`  int NOT NULL DEFAULT '0',
    PRIMARY KEY (`length`)
);

insert into fetal_lengths 
select `length`, count(*) as `count` 
from (select min(`length`) as `length` 
      from variants where for_ff=1 and chromosome not in ('X', 'Y') 
      group by `qname`) as qunique 
group by `length`;

commit;

insert into shared_lengths 
select `length`, count(*) as `count` 
from (select min(`length`) as `length` 
      from variants where for_ff=2 and chromosome not in ('X', 'Y') 
      group by `qname`) as qunique 
group by `length`;

commit;
