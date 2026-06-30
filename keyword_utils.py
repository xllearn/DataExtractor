from typing import Dict, List


SYNONYMS: Dict[str, List[str]] = {
    "医保": ["医疗保险", "基本医保", "医保基金"],
    "报销": ["报付", "支付", "补偿", "待遇"],
    "门诊": ["门特", "门诊统筹", "门诊慢特病"],
    "病种": ["疾病", "特殊病", "慢性病", "慢特病"],
    "起付标准": ["起付线", "起付金额"],
    "补助限额": ["封顶线", "最高支付限额", "年度限额"],
}


def split_keywords(keyword: str | None) -> List[str]:
    if not keyword:
        return []
    return [part.strip() for part in str(keyword).split() if part.strip()]


def expand_keyword_groups(keyword: str | None) -> List[List[str]]:
    groups: List[List[str]] = []
    for word in split_keywords(keyword):
        seen = set()
        group: List[str] = []
        for item in [word, *SYNONYMS.get(word, [])]:
            if item and item not in seen:
                group.append(item)
                seen.add(item)
        groups.append(group)
    return groups
