import os
import sys
import threading

from tqdm import tqdm

now_dir = os.getcwd()
sys.path.append(now_dir)

import re
import torch
from text.LangSegmenter import LangSegmenter
from text import chinese
from typing import Dict, List, Tuple
from text.cleaner import clean_text
from text import cleaned_text_to_sequence
from transformers import AutoModelForMaskedLM, AutoTokenizer
from TTS_infer_pack.text_segmentation_method import split_big_text, splits, get_method as get_seg_method

from tools.i18n.i18n import I18nAuto, scan_language_list

language = os.environ.get("language", "Auto")
language = sys.argv[-1] if sys.argv[-1] in scan_language_list() else language
i18n = I18nAuto(language=language)
punctuation = {"!", "?", "…", ",", ".", "-"}


def get_first(text: str) -> str:
    pattern = "[" + "".join(re.escape(sep) for sep in splits) + "]"
    text = re.split(pattern, text)[0].strip()
    return text


def merge_short_text_in_array(texts: str, threshold: int) -> list:
    if (len(texts)) < 2:
        return texts
    result = []
    text = ""
    for ele in texts:
        text += ele
        if len(text) >= threshold:
            result.append(text)
            text = ""
    if len(text) > 0:
        if len(result) == 0:
            result.append(text)
        else:
            result[len(result) - 1] += text
    return result


class TextPreprocessor:
    def __init__(self, bert_model: AutoModelForMaskedLM, tokenizer: AutoTokenizer, device: torch.device):
        self.bert_model = bert_model
        self.tokenizer = tokenizer
        self.device = device
        self.bert_lock = threading.RLock()

    def preprocess(self, text: str, lang: str, text_split_method: str, version: str = "v2") -> List[Dict]:
        print(f"############ {i18n('切分文本')} ############")
        text = self.replace_consecutive_punctuation(text)
        texts = self.pre_seg_text(text, lang, text_split_method)
        result = []
        # print(f"############ {i18n('提取文本Bert特征')} ############")
        # for text in tqdm(texts):
        #     phones, bert_features, norm_text = self.segment_and_extract_feature_for_text(text, lang, version)
        #     if phones is None or norm_text == "":
        #         continue
        #     res = {
        #         "phones": phones,
        #         "bert_features": bert_features,
        #         "norm_text": norm_text,
        #     }
        #     result.append(res)
        return result

    # def pre_seg_text(self, text: str, lang: str, text_split_method: str):
    #     text = text.strip("\n")
    #     if len(text) == 0:
    #         return []
    #     if text[0] not in splits and len(get_first(text)) < 4:
    #         text = "。" + text if lang != "en" else "." + text
    #     print(i18n("实际输入的目标文本:"))
    #     print(text)
    #
    #     seg_method = get_seg_method(text_split_method)
    #     text = seg_method(text)
    #
    #     while "\n\n" in text:
    #         text = text.replace("\n\n", "\n")
    #
    #     _texts = text.split("\n")
    #     _texts = self.filter_text(_texts)
    #     _texts = merge_short_text_in_array(_texts, 5)
    #     texts = []
    #
    #     for text in _texts:
    #         # 解决输入目标文本的空行导致报错的问题
    #         if len(text.strip()) == 0:
    #             continue
    #         if not re.sub("\W+", "", text):
    #             # 检测一下，如果是纯符号，就跳过。
    #             continue
    #         if text[-1] not in splits:
    #             text += "。" if lang != "en" else "."
    #
    #         # 解决句子过长导致Bert报错的问题
    #         if len(text) > 510:
    #             texts.extend(split_big_text(text))
    #         else:
    #             texts.append(text)
    #
    #     print(i18n("实际输入的目标文本(切句后):"))
    #     print(texts)
    #     return texts
    # 注:此处原有 `import re` / `import i18n` / `from typing import List` 三行,
    #    已删除 —— re 与 List 模块顶部(第 10/14 行)已导入;i18n 模块级(第 24 行)
    #    已是 I18nAuto 实例,而 `import i18n` 语义是"导入名为 i18n 的模块",
    #    环境无此模块,会在类体执行期抛 ModuleNotFoundError 导致整包 import 失败。

    # 定义标点常量（放到函数外，避免重复定义）
    splits = {"。", "！", "？", ".", "!", "?", ";", "；", "\n"}

    def get_first(text: str) -> str:
        """获取文本首个非空字符（辅助函数）"""
        return next((c for c in text if c.strip()), "")

    def get_seg_method(method: str):
        """获取切分方法（原函数依赖，保留）"""

        # 此处替换为实际的seg_method逻辑，示例返回原文本
        def default_seg(text):
            return text

        return default_seg

    def filter_text(texts: List[str]) -> List[str]:
        """过滤空文本（原函数依赖，保留）"""
        return [t.strip() for t in texts if t.strip()]

    def merge_short_text_in_array(texts: List[str], min_len: int) -> List[str]:
        """合并短文本（原函数依赖，保留）"""
        merged = []
        current = ""
        for text in texts:
            if len(current + text) < min_len:
                current += text
            else:
                if current:
                    merged.append(current)
                current = text
        if current:
            merged.append(current)
        return merged

    def split_big_text(text: str, max_len: int = 510) -> List[str]:
        """按标点智能切分长文本（替代原按长度硬切）"""
        if len(text) <= max_len:
            return [text]
        # 按中文标点切分，优先保留完整语义
        seg_pattern = re.compile(r'([。！？；，])')
        parts = seg_pattern.split(text)
        parts = [p for p in parts if p.strip()]
        # 重组文本，控制长度
        result = []
        current = ""
        for part in parts:
            if len(current + part) <= max_len:
                current += part
            else:
                if current:
                    result.append(current)
                current = part
        if current:
            result.append(current)
        return result

    def pre_seg_text(self, text: str, lang: str, text_split_method: str):
        """
        优化后的文本预处理切分函数
        - 移除无意义前缀
        - 智能补全结尾标点
        - 按语义切分长文本
        - 彻底过滤无效文本
        """
        # 基础清洗：移除换行符、首尾空格
        text = text.strip("\n").strip()
        if len(text) == 0:
            return []

        # 移除原逻辑中强制添加前缀标点的错误代码
        # ↓↓↓ 注释/删除这两行有问题的代码 ↓↓↓
        # if text[0] not in splits and len(get_first(text)) < 4:
        #     text = "。" + text if lang != "en" else "." + text

        print(i18n(f"实际输入的目标文本:{text}"))

        # 文本切分方法
        seg_method = get_seg_method(text_split_method)
        text = seg_method(text)

        # 清洗多余换行符
        while "\n\n" in text:
            text = text.replace("\n\n", "\n")

        # 切分+过滤空文本
        _texts = text.split("\n")
        _texts = self.filter_text(_texts)
        _texts = merge_short_text_in_array(_texts, 5)
        texts = []

        for t in _texts:
            # 彻底过滤空文本/纯符号文本
            clean_t = re.sub(r"\W+", "", t)  # 移除所有非文字字符
            if len(clean_t) == 0:
                continue

            # 智能补全结尾标点（仅当无结尾标点时补）
            last_char = t[-1]
            if lang != "en" and last_char not in {"。", "！", "？", "；"}:
                t += "。"
            elif lang == "en" and last_char not in {".", "!", "?", ";"}:
                t += "."

            # 长文本智能切分（按标点，而非硬切长度）
            if len(t) > 510:
                texts.extend(split_big_text(t))
            else:
                texts.append(t)

        # 最终过滤（防止空文本漏网）
        texts = [t.strip() for t in texts if t.strip()]

        # print(i18n("实际输入的目标文本(切句后):"))
        # print(texts)
        return texts
    def segment_and_extract_feature_for_text(
        self, text: str, language: str, version: str = "v1"
    ) -> Tuple[list, torch.Tensor, str]:
        return self.get_phones_and_bert(text, language, version)

    def get_phones_and_bert(self, text: str, language: str, version: str, final: bool = False):
        with self.bert_lock:
            text = re.sub(r' {2,}', ' ', text)
            textlist = []
            langlist = []
            if language == "all_zh":
                for tmp in LangSegmenter.getTexts(text,"zh"):
                    langlist.append(tmp["lang"])
                    textlist.append(tmp["text"])
            elif language == "all_yue":
                for tmp in LangSegmenter.getTexts(text,"zh"):
                    if tmp["lang"] == "zh":
                        tmp["lang"] = "yue"
                    langlist.append(tmp["lang"])
                    textlist.append(tmp["text"])
            elif language == "all_ja":
                for tmp in LangSegmenter.getTexts(text,"ja"):
                    langlist.append(tmp["lang"])
                    textlist.append(tmp["text"])
            elif language == "all_ko":
                for tmp in LangSegmenter.getTexts(text,"ko"):
                    langlist.append(tmp["lang"])
                    textlist.append(tmp["text"])
            elif language == "en":
                langlist.append("en")
                textlist.append(text)
            elif language == "auto":
                for tmp in LangSegmenter.getTexts(text):
                    langlist.append(tmp["lang"])
                    textlist.append(tmp["text"])
            elif language == "auto_yue":
                for tmp in LangSegmenter.getTexts(text):
                    if tmp["lang"] == "zh":
                        tmp["lang"] = "yue"
                    langlist.append(tmp["lang"])
                    textlist.append(tmp["text"])
            else:
                for tmp in LangSegmenter.getTexts(text):
                    if langlist:
                        if (tmp["lang"] == "en" and langlist[-1] == "en") or (tmp["lang"] != "en" and langlist[-1] != "en"):
                            textlist[-1] += tmp["text"]
                            continue
                    if tmp["lang"] == "en":
                        langlist.append(tmp["lang"])
                    else:
                        # 因无法区别中日韩文汉字,以用户输入为准
                        langlist.append(language)
                    textlist.append(tmp["text"])
            # print(textlist)
            # print(langlist)
            phones_list = []
            bert_list = []
            norm_text_list = []
            for i in range(len(textlist)):
                lang = langlist[i]
                phones, word2ph, norm_text = self.clean_text_inf(textlist[i], lang, version)
                bert = self.get_bert_inf(phones, word2ph, norm_text, lang)
                phones_list.append(phones)
                norm_text_list.append(norm_text)
                bert_list.append(bert)
            bert = torch.cat(bert_list, dim=1)
            phones = sum(phones_list, [])
            norm_text = "".join(norm_text_list)

            if not final and len(phones) < 6:
                return self.get_phones_and_bert("." + text, language, version, final=True)

            return phones, bert, norm_text

    def get_bert_feature(self, text: str, word2ph: list) -> torch.Tensor:
        with torch.no_grad():
            inputs = self.tokenizer(text, return_tensors="pt")
            for i in inputs:
                inputs[i] = inputs[i].to(self.device)
            res = self.bert_model(**inputs, output_hidden_states=True)
            res = torch.cat(res["hidden_states"][-3:-2], -1)[0].cpu()[1:-1]
        assert len(word2ph) == len(text)
        phone_level_feature = []
        for i in range(len(word2ph)):
            repeat_feature = res[i].repeat(word2ph[i], 1)
            phone_level_feature.append(repeat_feature)
        phone_level_feature = torch.cat(phone_level_feature, dim=0)
        return phone_level_feature.T

    def clean_text_inf(self, text: str, language: str, version: str = "v2"):
        language = language.replace("all_", "")
        phones, word2ph, norm_text = clean_text(text, language, version)
        phones = cleaned_text_to_sequence(phones, version)
        return phones, word2ph, norm_text

    def get_bert_inf(self, phones: list, word2ph: list, norm_text: str, language: str):
        language = language.replace("all_", "")
        if language == "zh":
            feature = self.get_bert_feature(norm_text, word2ph).to(self.device)
        else:
            feature = torch.zeros(
                (1024, len(phones)),
                dtype=torch.float32,
            ).to(self.device)

        return feature

    def filter_text(self, texts):
        _text = []
        if all(text in [None, " ", "\n", ""] for text in texts):
            raise ValueError(i18n("请输入有效文本"))
        for text in texts:
            if text in [None, " ", ""]:
                pass
            else:
                _text.append(text)
        return _text

    def replace_consecutive_punctuation(self, text):
        punctuations = "".join(re.escape(p) for p in punctuation)
        pattern = f"([{punctuations}])([{punctuations}])+"
        result = re.sub(pattern, r"\1", text)
        return result