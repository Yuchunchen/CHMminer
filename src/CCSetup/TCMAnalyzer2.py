# coding=utf-8
#
#
#    TCM Analyzer
#
#      這個程式放在高速電腦中心，提供 KNIME 呼叫，
#      KNIME 利用 exteranl SSH node 將 原始資料(OO)上傳到高速電腦中心，指定 inputFile, outputFile
#      程式會依序進行:
#         1) OO 檔上傳到 Hadoop 運算節點
#         2) 執行 ARminer 找出最常用的藥物組合，存成組合檔 (.rul)
#         4) 網路分析資料庫利用高速電腦平行運算進行藥物網路分析，存成一系列檔案 (.sna)
#


import argparse
import commands
import os, sys
import logging
import re
import snap
import unicodecsv
import simplejson as json
import io

from bitarray import bitarray
from pyspark import SparkContext, SparkConf
from pyspark.mllib.fpm import FPGrowth


#   1) OO 檔上傳到 Hadoop 運算節點
def UploadFile(srcFile):
    logger.info('[Hadoop] Uploading file {0} ....'.format(srcFile))
    srcFilepath, srcFilename = os.path.split(srcFile)
    (status, output) = commands.getstatusoutput('hadoop fs -test -e {0}'.format(srcFilename))
    if status==0:
        logger.info('[Hadoop] file {0} existed in Hadoop, code={1}.'.format(srcFilename, status))
        logger.info('[Hadoop] trying to remove file {0} from Hadoop...'.format(srcFilename))
        (status, output) = commands.getstatusoutput('hadoop fs -rm {0}'.format(srcFilename))
        logger.info('[Hadoop] file {0} removed from Hadoop, code={1}.'.format(srcFilename, status))
    logger.info('[Hadoop] trying to upload file {0} to Hadoop...'.format(srcFilename))
    logger.info('hadoop fs -put {0} {1}'.format(srcFile, srcFilename))
    (status, output) = commands.getstatusoutput('hadoop fs -put {0} {1}'.format(srcFile, srcFilename))
    if status==0:
        logger.info('[Hadoop] file {0} uploaded to Hadoop, code={1}.'.format(srcFilename, status))
        return status
    else:
        logger.info('[Hadoop] file {0} Fail to uploaded to Hadoop, code={1}.'.format(srcFilename, status))
        return None


def ARminer(srcFile, midFilename, indexOfDrug=1, minSupport=0.005, minConfidence=0.2, minLift=1.0):
    # type: (str, int, float, float, float, str) -> (object, str)
    """
        執行 ARminer 找出最常用的藥物組合，存成組合檔 (.rul)
        現在只找出 one-item set
    :rtype: object
    """
    srcFilepath, srcFilename = os.path.split(srcFile)
    conf = SparkConf().setAppName("pythonFP").set("spark.serializer", "org.apache.spark.serializer.JavaSerializer")
    sc = SparkContext(conf=conf)
    #sc.setLogLevel("ERROR")
    delimiter=re.compile(" +|,|\t", re.UNICODE)
    textdata = sc.textFile(srcFilename)
    data = textdata.map(lambda line: (re.split(delimiter, line.strip())[0], re.split(delimiter, line.strip())[indexOfDrug]))
    logger.info('[Spark] {0} lines loaded.'.format(data.count()))
    mycreateCombiner=lambda value: [value]
    mymergeValue=lambda c, value: c + [value]
    mymergeCombiner=lambda c1, c2: c1 + c2
    transactions=data.combineByKey(mycreateCombiner, mymergeValue, mymergeCombiner).map(lambda trasaction: list(set(trasaction[1])) )
    num_transactions=transactions.count()
    logger.info('[Spark] {0} transactions.'.format(num_transactions))
    model = FPGrowth.train(transactions, minSupport, numPartitions=10)
    result_freqItemsets = model.freqItemsets().collect()
    one_itemset_list=sorted(map(lambda itemset: itemset.items[0], 
                                filter(lambda itemset: len(itemset.items)==1,  result_freqItemsets)))
    number_of_itemset = len(one_itemset_list)
    oneitem_bit={}    # item to bit lookup dictionary
    oneitem_loc={}    # item to number of location
    bit_oneitem={}    # bit to item lookup dictionary
    for i in xrange(0, number_of_itemset):                  #將 item 編成 bitarray
        the_bit= number_of_itemset * bitarray('0')
        the_bit[i]=True
        oneitem_bit[one_itemset_list[i]]=the_bit            # item --> bitarray
        oneitem_loc[one_itemset_list[i]]=i                  # item --> 位置
        bit_oneitem[the_bit.tobytes()]=one_itemset_list[i]  # bitarray --> item
    bit_count={}

    def itemset2bit(items):
        "Convert itemsets to a bitarray"
        the_bit = number_of_itemset * bitarray('0')
        for i in items:
            the_bit[oneitem_loc[i]] = True
        return the_bit

    for itemset in result_freqItemsets:
        the_bit=itemset2bit(itemset.items)
        bit_count[the_bit.tobytes()]=itemset.freq
    #Generate association rules from candidate itemsets

    SNAnodes={}
    SNAedges=[["source", "target", 
               "sourceLabel", "targetLabel", 
               "itemsetSupport", "itemsetSupportPercent", 'itemsetLift']]
    associationRules=[["LHS", "RHS", 'LHSname', 'RHSname', "n_LHS", "n_RHS", "num_transactions", "num_LHS", "num_RHS", "num_LHSRHS", "Support", "Confidence", "Lift", "Conviction"]]
    for itemset in result_freqItemsets:
        # associationRules.append(["" ,  ",".join(sorted(itemset.items)) ,
        #                          0, len(itemset.items), num_transactions, num_transactions, itemset.freq,  itemset.freq,
        #                                                 1.0* itemset.freq/num_transactions,
        #                                                 1.0* itemset.freq/num_transactions,
        #                                                 1  ])
        for LHS in itemset.items:
            num_LHS = bit_count[oneitem_bit[LHS].tobytes()]
            RHS = filter(lambda x: x!=LHS, itemset.items)
            RHS_bit=itemset2bit(RHS)
            if len(RHS) == 1:         # 只找 1->1 rule    如果改成 len(RHS)>0  則可以找出 所有 rules
                num_RHS = bit_count[RHS_bit.tobytes()]
                # print "\t".join([LHS , "=>" ,  ",".join(sorted(RHS)) , str(num_transactions), str(num_LHS), str(num_RHS),  str(itemset.freq) ])
                # print "\t".join([oneitem_bit[LHS].to01() , "=>" ,  RHS_bit.to01() , str(num_transactions), str(num_LHS), str(num_RHS),  str(itemset.freq) ])
                theSupport = 1.0 * itemset.freq / num_transactions
                theConfidence=1.0* itemset.freq / num_LHS
                theLift =  1.0* num_transactions * itemset.freq / (num_LHS * num_RHS)
                if theConfidence > minConfidence and theLift > minLift:
                    associationRules.append([LHS,  ",".join(sorted(RHS)), len([LHS]), len(RHS),
                                         num_transactions, num_LHS, num_RHS, itemset.freq,
                                         theSupport,                   # support
                                         theConfidence,                # confidence
                                         theLift,                      # lift
                                         (1-1.0*num_RHS/num_transactions)/(1-theConfidence)    ])      # Conviction
                    SNAnodes[LHS] = [oneitem_loc[LHS], LHS, num_LHS, num_LHS*100.0/num_transactions]
                    SNAnodes[RHS[0]] = [oneitem_loc[RHS[0]], RHS[0], num_RHS, num_RHS*100.0/num_transactions]
                    SNAedges.append([SNAnodes[LHS][0],  SNAnodes[RHS[0]][0],    # source, target
                                     LHS, RHS[0],                               # sourceLabel, targetLabel
                                     itemset.freq,
                                     theSupport * 100.0, theLift])              # support, Lift

    rulFilename=os.path.join(srcFilepath, srcFilename + midFilename +".rul")
    with open(rulFilename,'wb') as f:
        w = unicodecsv.writer(f, encoding='utf-8', delimiter="\t")
        w.writerows(associationRules)
    logger.info('[Spark] Association rule file {0} saved with Support={1}, Confidence={2}'.format(rulFilename, minSupport, minConfidence))
    sc.stop()
    SNAedgefile=os.path.join(srcFilepath, srcFilename + midFilename+ ".snaedge")
    with open(SNAedgefile,'wb') as f:
        w = unicodecsv.writer(f, encoding='utf-8', delimiter=" ")
        w.writerows(SNAedges)
    logger.info('[Spark] SNA edge file {0} saved.'.format(SNAedgefile))
    theSNAnodes ={}
    for node in SNAnodes.itervalues():
        theSNAnodes[node[0]]=node
    #SNAnodefile=srcFile + ".snanode"
    #with open(SNAnodefile,'wb') as f:                                     #--- > 此時尚無需寫入
    #    w = unicodecsv.writer(f, encoding='utf-8', delimiter=" ")
    #    w.writerows(SNAnodes.values())
    #logger.info('[Spark] SNA node file {0} saved.'.format(SNAnodefile))
    return (associationRules, rulFilename, SNAedges, SNAedgefile, theSNAnodes)


#   4) 網路分析資料庫利用高速電腦平行運算進行藥物網路分析，存成一系列檔案 (.sna)
def SNAminer(SNAedgefile, SNAnodes, midFilename):
    #藥物屬性 (5氣 5味 12經絡)
    TCMfeature={}
    lenOfTCMfeature=0
    with open('metadata.DRUG.feature.TCM.summary.level123.QiFlavorMeri.20170621.csv','rb') as f:
        reader = unicodecsv.reader(f, encoding='utf-8', delimiter=",")
        for row in reader:
            if row[0].upper()=='DRUGNAME':
                continue 
            TCMfeature[row[0]]=row[1:]
            if len(row)-1 > lenOfTCMfeature:
                lenOfTCMfeature=len(row)-1
    emptyTCMfeatureList=[ -1 ] * lenOfTCMfeature
    #藥物英文名稱 (latin, pinyin, kampo, 搜尋詞= "latin" OR "pinyin" OR "kampo" without null )
    TCMtranslation={}
    with open('metadata.DRUG.NAME.translation_shortform.20170625.tab','rb') as f:
        reader = unicodecsv.reader(f, encoding='utf-8', delimiter="\t")
        for row in reader:
            if row[0].upper()=='TYPE':
                continue 
            searchTerms= [row[2].strip(" \t""").replace(" ","-"), row[3].strip(" \t""").replace(" ","-"), row[4].strip(" \t""").replace(" ","-")]   # latin, pinyin, kampo
            searchTerms= ['"'+x+'"' for x in searchTerms if len(x) > 0]                        
            theSearchTerm1=" OR ".join(searchTerms)                          # searchTerm1
            logger.info("theSearchTerm1 is :" + theSearchTerm1)
            searchTerms=searchTerms.append(row[1].strip(" \t"""))
            #theSearchTerm2=' '.join(searchTerms)   # searchTerm2 for google
            #logger.info("theSearchTerm2 is :" + theSearchTerm2)
            TCMtranslation[row[1].strip(" \t""")]=[row[2].strip(" \t""").replace(" ","-"), row[3].strip(" \t""").replace(" ","-"), row[4].strip(" \t""").replace(" ","-"), 
                                                   theSearchTerm1, row[1].strip(" \t""")]
                                 # 此處 theSearchTerm2 一直有問題
    emptyTCMtranslation=[ '' ] * 5
    #開始載入edge資料
    theGraph = snap.LoadEdgeList(snap.PUNGraph, SNAedgefile, 0, 1)
    logger.info("[SNA] Nodes %d, Edges %d" % (theGraph.GetNodes(), theGraph.GetEdges()))
    
    CmtyV = snap.TCnComV()
    modularity = snap.CommunityCNM(theGraph, CmtyV)
    groupNo=0
    for Cmty in CmtyV:
        for NI in Cmty:
            SNAnodes[NI].append("G{0}".format(groupNo))
            SNAnodes[NI].extend(TCMfeature.get(SNAnodes[NI][1], emptyTCMfeatureList)) ##如果TCMfeature找不到，填 -1 
            SNAnodes[NI].extend(TCMtranslation.get(SNAnodes[NI][1], emptyTCMtranslation)) ##如果TCMtranslation找不到，填 空白 
        groupNo+=1
    logger.info("The modularity of the network is %f" % modularity)
    filepath_name=os.path.splitext(SNAedgefile)[0]
    

    SNAnodefile= os.path.join( filepath_name + ".snanode")
    with open(SNAnodefile,'wb') as f:
        f.write("\t".join(['id', 'nodeLabel', 'nodeSupport', 'nodeSupportPercent', 'myGroup',
                           'qiHOT', 'qiWARMTH', 'qiFAIR', 'qiCOOLNESS', 'qiCOLD',
                           'flavorPUNGENCY', 'flavorSWEETNESS', 'flavorSOURNESS', 'flavorBITTERNESS','flavorSALTINESS',
                           'meridianLIVER', 'meridianHEART', 'meridianSPLEEN', 'meridianLUNG', 'meridianKINDEY', 
                           'meridianGB','meridianSI','meridianLI','meridianST','meridianUB','meridianPERI','meridianTE',
                           'latin', 'pinyin', 'kampo', 'theSearchTerm1', 'theSearchTerm2'])+"\n")
        w = unicodecsv.writer(f, encoding='utf-8', delimiter=" ")
        w.writerows(SNAnodes.values())
    logger.info('[SNA] SNA node file {0} saved.'.format(SNAnodefile))


def output2cyjs(srcFile, SNAnodes, SNAedges, midFilename):
    srcFilepath, srcFilename = os.path.split(srcFile)
    
    the_cyjs_network = {
        'data': {
            'name': '',
            'collection': ''
        },
        'elements': {
            'nodes': [],
            'edges': []
        }
    }
    the_cyjs_network['data']['name'] = midFilename
    the_cyjs_network['data']['collection'] = srcFilename
    
    build_node = lambda x: { 'data': 
                                  {'id': x[0], 'name': x[0],
                                   'nodeLabel' : x[1],
                                   'nodeSupport': x[2],
                                   'nodeSupportPercent': x[3],
                                   'myGroup': x[4],
                                   'qiHOT' :  x[5] ,
                                   'qiWARMTH' :  x[6] ,
                                   'qiFAIR' :   x[7],
                                   'qiCOOLNESS' :   x[8],
                                   'qiCOLD' :   x[9],
                                   'flavorPUNGENCY' :   x[10],
                                   'flavorSWEETNESS' :   x[11],
                                   'flavorSOURNESS' :   x[12],
                                   'flavorBITTERNESS' :   x[13],
                                   'flavorSALTINESS' :   x[14],
                                   'meridianLIVER' :   x[15],
                                   'meridianHEART' :   x[16],
                                   'meridianSPLEEN' :   x[17],
                                   'meridianLUNG' :   x[18],
                                   'meridianKINDEY' :   x[19],
                                   'meridianGB' :   x[20],
                                   'meridianSI' :   x[21],
                                   'meridianLI' :   x[22],
                                   'meridianST' :   x[23],
                                   'meridianUB' :   x[24],
                                   'meridianPERI' :   x[25],
                                   'meridianTE': x[26],
                                   'latin'     : x[27],
                                   'pinyin'    : x[28],
                                   'kampo'     : x[29],
                                   'theSearchTerm1' : x[30],
                                   'theSearchTerm2' : x[31]
                                   }
                           }
    
    build_edge = lambda e: { 'data': 
                             {'source': e[0], 'target': e[1],
                              'sourceLabel': e[2], 'targetLabel': e[3],
                              "itemsetSupport": e[4],
                              "itemsetSupportPecent": e[5],
                              "itemsetLift": e[6]
                             } }
    the_cyjs_network['elements']['nodes']=list(map(build_node, SNAnodes.values()))
    the_cyjs_network['elements']['edges']=list(map(build_edge, SNAedges[1:]))
    
    with io.open(srcFile + midFilename+'.json', 'w', encoding='utf8') as json_file:
        data = json.dumps(the_cyjs_network, ensure_ascii=False, encoding='utf-8', use_decimal=True)
        # unicode(data) auto-decodes data to unicode if str
        json_file.write(unicode(data))
    # spark-submit TCMAnalyzer2.py /home_i1/y23ycc01/incoming/tid.acne.csv  4 0.01 0.4

def main():
    parser = argparse.ArgumentParser(description="Analyze TCM network")
    parser.add_argument("inputFile", help="Input file with full absolute path")
    parser.add_argument("IndexofDrugField", help="Index number of field contains drug (number starts from 0. eg. 0, 1,2,3...)", type=int, default=1)
    parser.add_argument("minSupp", help="minSupport", type=float, default=0.005)
    parser.add_argument("minConf", help="minConfidence", type=float, default=0.2)
    args = parser.parse_args()
    srcFile=args.inputFile
    theIndexOfDrug = args.IndexofDrugField
    the_minSupport = args.minSupp
    the_minConfidence = args.minConf

    srcFilepath, srcFilename = os.path.split(srcFile)
    midFilename = 'S{0:04d}p_C{1:02d}p'.format(int(the_minSupport*10000), int(the_minConfidence * 100))
    #step 1. .csv  上傳到 Hadoop 中
    UploadFile(srcFile)
    #step 2. 找出 frequent itemset and rules
    (associationRules, rulFilename, SNAedges, SNAedgefile, SNAnodes)=ARminer(srcFile,  midFilename, theIndexOfDrug, the_minSupport , the_minConfidence, minLift=1.0)
    #step 3. 找cluster
    SNAminer(SNAedgefile, SNAnodes, midFilename)
    #step 4. 輸出 cyjs 檔案
    output2cyjs(srcFile, SNAnodes,SNAedges, midFilename)



if __name__=='__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S', filename="debug.log")
    logger = logging.getLogger('TCMAnalyzer')
    main()
    sys.exit(0)