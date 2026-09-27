# Data Profile Report -- Business Entity Resolution

```
=================================================================
STEPS 1-3: LOAD, VALIDATE, NORMALIZE, SAVE (one file at a time)
=================================================================

--- S1 : train_source1.tsv ---
  Loading ...
  Loaded  2,206,821 rows x 4 cols  (5.6s)
  Nulls   : {'entity_id': 0, 'business_name': 0, 'business_address': 0, 'country': 0}
  Dup IDs : 0   Bad prefix: 0
  Countries: {'US': 1323633, 'India': 883188}
  Normalizing ...
  Normalized in 75.8s
  Garbled names: 0   Empty normalized: 0   Empty core: 1849
  Saving -> train_source1_clean.tsv ...
  Done in 103.9s total.  Saved 2,206,821 rows x 13 cols.

--- S2 : train_source2.tsv ---
  Loading ...
  Loaded  5,034,616 rows x 4 cols  (12.7s)
  Nulls   : {'entity_id': 0, 'business_name': 2, 'business_address': 168967, 'country': 0}
  Dup IDs : 0   Bad prefix: 0
  Countries: {'US': 3016817, 'India': 2017799}
  Normalizing ...
  Normalized in 243.1s
  Garbled names: 0   Empty normalized: 2   Empty core: 1201
  Saving -> train_source2_clean.tsv ...
  Done in 314.0s total.  Saved 5,034,616 rows x 13 cols.

--- S3 : train_source3.tsv ---
  Loading ...
  Loaded  5,285,603 rows x 4 cols  (13.7s)
  Nulls   : {'entity_id': 0, 'business_name': 13, 'business_address': 175916, 'country': 0}
  Dup IDs : 0   Bad prefix: 0
  Countries: {'US': 3170056, 'India': 2115547}
  Normalizing ...
  Normalized in 221.7s
  Garbled names: 0   Empty normalized: 13   Empty core: 2555
  Saving -> train_source3_clean.tsv ...
  Done in 354.0s total.  Saved 5,285,603 rows x 13 cols.

--- GT : train_ground_truth.tsv ---
  Loaded  2,206,821 rows
  Saved -> train_ground_truth_clean.tsv

--- S1 : test_source1.tsv ---
  Loading ...
  Loaded  1,732,544 rows x 4 cols  (7.9s)
  Nulls   : {'entity_id': 0, 'business_name': 0, 'business_address': 0, 'country': 0}
  Dup IDs : 0   Bad prefix: 0
  Countries: {'India': 809986, 'US': 663106, 'France': 259452}
  Normalizing ...
  Normalized in 127.5s
  Garbled names: 0   Empty normalized: 0   Empty core: 1617
  Saving -> test_source1_clean.tsv ...
  Done in 164.5s total.  Saved 1,732,544 rows x 13 cols.

--- S2 : test_source2.tsv ---
  Loading ...
  Loaded  4,887,273 rows x 4 cols  (13.0s)
  Nulls   : {'entity_id': 0, 'business_name': 46, 'business_address': 129408, 'country': 0}
  Dup IDs : 0   Bad prefix: 0
  Countries: {'India': 2312565, 'US': 1871330, 'France': 703378}
  Normalizing ...
  Normalized in 208.8s
  Garbled names: 0   Empty normalized: 46   Empty core: 1308
  Saving -> test_source2_clean.tsv ...
  Done in 290.1s total.  Saved 4,887,273 rows x 13 cols.

--- S3 : test_source3.tsv ---
  Loading ...
  Loaded  5,082,316 rows x 4 cols  (13.7s)
  Nulls   : {'entity_id': 0, 'business_name': 59, 'business_address': 136098, 'country': 0}
  Dup IDs : 0   Bad prefix: 0
  Countries: {'India': 2405000, 'US': 1945701, 'France': 731615}
  Normalizing ...
  Normalized in 192.2s
  Garbled names: 0   Empty normalized: 59   Empty core: 2842
  Saving -> test_source3_clean.tsv ...
  Done in 265.2s total.  Saved 5,082,316 rows x 13 cols.

=================================================================
STEP 2: COUNTRY AUDIT
=================================================================

  train_source1_clean.tsv:
    'US'                           -> 1,323,633
    'India'                        ->  883,188

  train_source2_clean.tsv:
    'US'                           -> 3,016,817
    'India'                        -> 2,017,799

  train_source3_clean.tsv:
    'US'                           -> 3,170,056
    'India'                        -> 2,115,547

  test_source1_clean.tsv:
    'India'                        ->  809,986
    'US'                           ->  663,106
    'France'                       ->  259,452

  test_source2_clean.tsv:
    'India'                        -> 2,312,565
    'US'                           -> 1,871,330
    'France'                       ->  703,378

  test_source3_clean.tsv:
    'India'                        -> 2,405,000
    'US'                           -> 1,945,701
    'France'                       ->  731,615

  Countries in TEST only (unseen in train): {'France'}

=================================================================
STEP 3b: GROUND TRUTH MATCH-COUNT DISTRIBUTION
=================================================================
  n_matches | count
            0 |    123,247
            1 |    119,157
            2 |    375,212
            3 |    530,841
            4 |    484,115
            5 |    321,957
            6 |    164,868
            7 |     63,968
            8 |     18,680
            9 |      4,205
           10 |        534
           11 |         37

  S1 with 0 matches (singletons): 0
  S1 with >=1 match             : 2,206,821
  Total S1                      : 2,206,821

=================================================================
STEP 4: NORMALIZATION SANITY CHECK (10 matched pairs)
=================================================================

  [1] S1=S1-777210964 -> matched=S2-12029274
       RAW  name S1 : 'Davis Family Office'
       NORM name S1 : 'davis family office'
       CORE name S1 : 'davis family office'
       RAW  name TGT: 'Davis Family Offie'
       NORM name TGT: 'davis family offie'
       CORE name TGT: 'davis family offie'
       RAW  addr S1 : '88 Olive Circle, Lebanon, TN'
       NORM addr S1 : '88 olive circle, lebanon, tn'
       RAW  addr TGT: '88 OLIVE CIR, LEBANON, TN'
       NORM addr TGT: '88 olive circle, lebanon, tn'

  [2] S1=S1-190133982 -> matched=S2-523219173
       RAW  name S1 : 'MS Consultancy Corp'
       NORM name S1 : 'ms consultancy corp'
       CORE name S1 : 'ms consultancy'
       RAW  name TGT: 'MS [Consultancy]'
       NORM name TGT: 'ms consultancy'
       CORE name TGT: 'ms consultancy'
       RAW  addr S1 : 'Shymala Appts 1St Floor Flat No. 4 Opp Ratna Hospital Sb Road In Haveli, Pune, Maharashtra'
       NORM addr S1 : 'shymala appts 1st floor flat number 4 opp ratna hospital sb road in haveli, pune, maharashtra'
       RAW  addr TGT: 'SHYMALA APPTS 1-1ST FLOOR FLAT NO. 4 OPP RATNA HOSPITAL SB ROAD IN HAVELI, PUNE, Maharashtra'
       NORM addr TGT: 'shymala appts 1 1st floor flat number 4 opp ratna hospital sb road in haveli, pune, maharashtra'

  [3] S1=S1-970131671 -> matched=S2-670035601
       RAW  name S1 : '3520 Main Road Realty Inc'
       NORM name S1 : '3520 main road realty inc'
       CORE name S1 : '3520 main road realty'
       RAW  name TGT: '3520 MAIN ROAD REALTY INC'
       NORM name TGT: '3520 main road realty inc'
       CORE name TGT: '3520 main road realty'
       RAW  addr S1 : 'TX, 158 Simpson Lane, Somerset'
       NORM addr S1 : 'tx, 158 simpson lane, somerset'
       RAW  addr TGT: 'SIMPSON LANE, SOMERSET, TX'
       NORM addr TGT: 'simpson lane, somerset, tx'

  [4] S1=S1-391999301 -> matched=S2-742819060
       RAW  name S1 : 'Team Air Pvt. Ltd.'
       NORM name S1 : 'team air pvt ltd'
       CORE name S1 : 'team air'
       RAW  name TGT: 'TEAMAIR.COM'
       NORM name TGT: 'teamair com'
       CORE name TGT: 'teamair com'
       RAW  addr S1 : 'Flat No:101, Anuska Towers, Opp. Mercedes Benz Show Room, Lakdi- Ka, -Pool, Hyderabad, Telangana'
       NORM addr S1 : 'flat number 101, anuska towers, opp mercedes benz show room, lakdi ka, pool, hyderabad, telangana'
       RAW  addr TGT: 'FLAT NO:101, ANUSKA TOWERS, OPP. MERCEDES BENZ SHOW ROOM, LAKDI- KA, -POOL, తెలంగాణ'
       NORM addr TGT: 'flat number 101, anuska towers, opp mercedes benz show room, lakdi ka, pool, త ల గ ణ'

  [5] S1=S1-435988542 -> matched=S2-500704398
       RAW  name S1 : 'Drayex Berto LLC'
       NORM name S1 : 'drayex berto llc'
       CORE name S1 : 'drayex berto'
       RAW  name TGT: 'DRAYEX  BERTO LLC'
       NORM name TGT: 'drayex berto llc'
       CORE name TGT: 'drayex berto'
       RAW  addr S1 : 'Montgomery Village, MD, 19821 Wheelwright Drive'
       NORM addr S1 : 'montgomery village, md, 19821 wheelwright drive'
       RAW  addr TGT: '##19821 WHEELWRIGHT DR, MONTGOMERY VILLAGE, MD'
       NORM addr TGT: '19821 wheelwright drive, montgomery village, md'

  [6] S1=S1-351020560 -> matched=S2-907008976
       RAW  name S1 : 'Grand Connecticut LLC'
       NORM name S1 : 'grand connecticut llc'
       CORE name S1 : 'grand connecticut'
       RAW  name TGT: 'Grand Connecticut'
       NORM name TGT: 'grand connecticut'
       CORE name TGT: 'grand connecticut'
       RAW  addr S1 : 'Calumet City, 351 Hoxie Avenue, IL'
       NORM addr S1 : 'calumet city, 351 hoxie avenue, il'
       RAW  addr TGT: 'CALUMET CITY, 351 HOXIE AVE, N/A, IL'
       NORM addr TGT: 'calumet city, 351 hoxie avenue, north a, il'

  [7] S1=S1-353020204 -> matched=S2-403125820
       RAW  name S1 : 'Prairie Capital Partners PLLC'
       NORM name S1 : 'prairie capital partners pllc'
       CORE name S1 : 'prairie capital partners'
       RAW  name TGT: 'PRAIRIE CAPITAL PLLC-PARTNERS'
       NORM name TGT: 'prairie capital pllc partners'
       CORE name TGT: 'prairie capital pllc partners'
       RAW  addr S1 : '120 Autumn Woods Boulevard, Mount Holly, NC'
       NORM addr S1 : '120 autumn woods boulevard, mount holly, nc'
       RAW  addr TGT: '120. Autumn Woods Boulevard, MOUNT HOLLY, NC'
       NORM addr TGT: '120 autumn woods boulevard, mount holly, nc'

  [8] S1=S1-374388852 -> matched=S2-509116615
       RAW  name S1 : 'Jalna Chem LLP'
       NORM name S1 : 'jalna chem llp'
       CORE name S1 : 'jalna chem'
       RAW  name TGT: 'Jalna Chem  LLP'
       NORM name TGT: 'jalna chem llp'
       CORE name TGT: 'jalna chem'
       RAW  addr S1 : 'At H. No 211, Bhamberi Tq. Ambad S/Dn Dist Jalna, Jalna, Maharashtra'
       NORM addr S1 : 'at h number 211, bhamberi tq ambad south dn district jalna, jalna, maharashtra'
       RAW  addr TGT: 'AT H. NO 211, BHAMBERI TQ. AMBAD S/DN DIST JALNA, JALNA, Maharashtra'
       NORM addr TGT: 'at h number 211, bhamberi tq ambad south dn district jalna, jalna, maharashtra'

  [9] S1=S1-793615008 -> matched=S2-102911781
       RAW  name S1 : 'Clairvoyant Record Private Limited'
       NORM name S1 : 'clairvoyant record private limited'
       CORE name S1 : 'clairvoyant record'
       RAW  name TGT: 'Clairvoyant Ride Private (Limited)'
       NORM name TGT: 'clairvoyant ride private limited'
       CORE name TGT: 'clairvoyant ride'
       RAW  addr S1 : '1St Floor, Tamrakarmall, New Bus Stand, Sehore, Madhya Pradesh'
       NORM addr S1 : '1st floor, tamrakarmall, new bus stand, sehore, madhya pradesh'
       RAW  addr TGT: 'NO 7-1ST FLOOR, TAMRAKARMALL, NEW BUS STAND, SEHORE, Madhya Pradesh'
       NORM addr TGT: 'number 7 1st floor, tamrakarmall, new bus stand, sehore, madhya pradesh'

  [10] S1=S1-339384180 -> matched=S2-763394237
       RAW  name S1 : 'FH Business Pvt Ltd'
       NORM name S1 : 'fh business pvt ltd'
       CORE name S1 : 'fh business'
       RAW  name TGT: 'FH BUSINESS PVT LIMITED'
       NORM name TGT: 'fh business pvt limited'
       CORE name TGT: 'fh business'
       RAW  addr S1 : '602, 6Th Floor, Crystal Mall, Bani Park, Jaipur, Rajasthan'
       NORM addr S1 : '602, 6th floor, crystal mall, bani park, jaipur, rajasthan'
       RAW  addr TGT: '602, 6TH FLOOR, CRYSTAL MALL, BANI PARK, JAIPUR, राजस्थान'
       NORM addr TGT: '602, 6th floor, crystal mall, bani park, jaipur, र जस थ न'

=================================================================
STEP 5: SUMMARY
=================================================================

  File                                         Rows  Cols   Secs  Garbled  EmptyNorm
  --------------------------------------------------------------------------------
  train_source1_clean.tsv                 2,206,821    13  103.9        0          0
  train_source2_clean.tsv                 5,034,616    13  314.0        0          2
  train_source3_clean.tsv                 5,285,603    13  354.0        0         13
  test_source1_clean.tsv                  1,732,544    13  164.5        0          0
  test_source2_clean.tsv                  4,887,273    13  290.1        0         46
  test_source3_clean.tsv                  5,082,316    13  265.2        0         59

  All clean files saved to: C:\Users\indhu\Downloads\ML Project\dataset\clean

```
