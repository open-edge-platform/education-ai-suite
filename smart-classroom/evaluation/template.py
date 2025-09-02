templ_sum_en = """\
You are an expert teaching assistant. Given the following transcript of a lecture, generate a concise summary that captures the main points, key arguments, and important details. Avoid copying text verbatim and write the summary in your own words.

Transcript:
{transcript}

Summary:
"""


templ_sum_zh = """\
你的任务是根据提供的原始课堂音频的转录文本，提炼出本节课的核心内容、知识点结构、讲解顺序，并用简洁清晰的语言进行总结。尤其注意不要捏造任何没有提及的知识点，保证知识点真实准确，避免任何冗余或误导性内容。

原始课堂音频转录文本:
"{transcript}"

总结：

"""

templ_score_en = """\
You job is to score a summary about a lecture.
The original lecture audio transcript is provided. 
Based on the transcript, you need to briefly describe your judgment and after that, produce a score on the scale of 1 to 100 to reflect the accuray and integrity of the summary.


Original lecture audio transcript:
"{transcript}"



Summary:
"{summary}"


"""


templ_score_zh = """\
你的任务是评价一份关于课堂教学内容的总结。
你需要根据提供的原始课堂音频的转录文本，评价这份总结的质量，评价的主要标准是总结内容的准确性与完整性。
简单描述评价理由后，输出一个1到100的分数。



原始课堂音频转录文本:
"{transcript}"



课堂总结:
"{summary}"


"""