# -*- coding: utf-8 -*-
"""用 Word COM 把项目简介文档导出为 PDF（原生支持中文路径）。

Word 打开时会自动更新目录域（脚本已在 docx 中设置 w:updateFields），
因此导出的 PDF 目录带真实页码。
"""
import os
import sys
import time

import win32com.client as wc

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 默认导出项目简介文档；可传两个参数：源 docx 名、输出 pdf 名
SRC_NAME = (sys.argv[1] if len(sys.argv) > 1
            else '基于改进 YOLO 与步态分析的老龄人群跌倒风险预测系统-项目简介文档.docx')
OUT_NAME = sys.argv[2] if len(sys.argv) > 2 else 'brief.pdf'
SRC = os.path.join(BASE, SRC_NAME)
OUT = os.path.join(BASE, 'preview', OUT_NAME)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
if os.path.exists(OUT):
    os.remove(OUT)

WD_FORMAT_PDF = 17

app = wc.Dispatch('Word.Application')
app.Visible = False
app.DisplayAlerts = 0

doc = app.Documents.Open(SRC, False, True)
try:
    print('打开成功，页数 =', doc.ComputeStatistics(2))
except Exception as e:
    print('页数统计失败:', e)

# 立即更新所有域（含目录），确保 PDF 中的目录页码是真实页码
try:
    doc.Fields.Update()
    for toc in doc.TablesOfContents:
        toc.Update()
    print('目录域已更新')
except Exception as e:
    print('目录更新失败（可忽略）:', str(e)[:120])

ok = False
attempts = [
    ('SaveAs2', lambda: doc.SaveAs2(OUT, WD_FORMAT_PDF)),
    ('SaveAs', lambda: doc.SaveAs(OUT, WD_FORMAT_PDF)),
    ('ExportAsFixedFormat', lambda: doc.ExportAsFixedFormat(OUT, WD_FORMAT_PDF)),
]
for name, fn in attempts:
    if ok:
        break
    try:
        fn()
        if os.path.exists(OUT):
            ok = True
            print('导出方式 =', name)
    except Exception as e:
        print('%s 失败: %s' % (name, str(e)[:110]))

if not ok:
    try:
        doc.PrintOut(False, False, 0, '', 'Microsoft Print to PDF',
                     True, 0, '', OUT)
        for _ in range(30):
            time.sleep(2)
            if os.path.exists(OUT) and os.path.getsize(OUT) > 0:
                ok = True
                break
        print('导出方式 = PrintOut' if ok else 'PrintOut 未产出文件')
    except Exception as e:
        print('PrintOut 失败: %s' % str(e)[:110])

try:
    doc.Close(0)
except Exception:
    pass
try:
    app.Quit()
except Exception:
    pass

print('结果 =', 'PDF 已生成' if os.path.exists(OUT) else 'PDF 缺失')
if os.path.exists(OUT):
    print('大小 = %.1f KB' % (os.path.getsize(OUT) / 1024.0))
