import jieba
from .settings import TOPICS

KEYWORDS=[['中医','中药','民族医'],['医疗质量','医疗服务','诊疗','护理','医院','基层医疗'],['医师','执业','医疗机构','护士','人事'],['信息化','信息系统','数据','标准'],['监督','执法','处罚','法治'],['儿童','妇幼','生育','人口','母婴','幼儿'],['疾病','传染病','疾控','公共卫生','预防接种'],['健康促进','健康素养','健康中国']]
def tokens(text):return ' '.join(jieba.cut_for_search(text))
def classify(title,body):
    scores=[sum((3 if k in title else 0)+min(body.count(k),3) for k in words) for words in KEYWORDS]
    best=max(scores)
    if best==0:return '',[]
    idx=scores.index(best)
    return TOPICS[idx],[k for k in KEYWORDS[idx] if k in title+body]
