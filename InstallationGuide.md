# installation guide #
## Reruirment ##
The system requires you have:

1. Access right to Computer center (台灣國網中心)
2. A Windows-based computer with administration access right
	* 

The whole installation process has two parts: 1) Computing Node computer center and 2) local installation
## Computer Center ##
1. Standard configuration as Computer center (台灣國網中心)
2. Upload the following files to your $HOME directory 
	1. TCMAnalyzer2.py
	2. snap.py   (Stanford's SNAP library [https://snap.stanford.edu/](https://snap.stanford.edu/ "Stanford SNAP library") )
	3. snap.pyc  (Stanford's SNAP library [https://snap.stanford.edu/](https://snap.stanford.edu/ "Stanford SNAP library") )
3. Install Python library (for Python 2.6 台灣國網中心)
  * pip install --user argparse
  * pip install --user json
  * pip install --user unicodecsv
  * pip install --user bitarray 
4. Upload metadata files to $HOME directory (please pick the file with latest date if multiple)
	1. metadata.DRUG.NAME.translation_shortform.20170625.tab
	2. metadata.DRUG.feature.TCM.summary.level123.QiFlavorMeri.20170621.csv
3. Create a working directory under $HOME directory
	* you may have $HOME/incoming for example
	* just leave the working directory empty
    
