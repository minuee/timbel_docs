# -*- coding: utf-8 -*-
filepath = r'C:\Users\Owner\Desktop\workspace\aicc-workspace\aicm-pair\docs\01-requirements\flows\search-rag\04-search-tuning.md'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

old = '|| \ud0d0\uc0c9\uc801 \uac80\uc0c9 (\ub113\uc740 \ubc94\uc704) | 0.60 | \uc7ac\ud604\uc728 \uc6b0\uc120 |'
new = '|| \ud0d0\uc0c9\uc801 \uac80\uc0c9 (\ub113\uc740 \ubc94\uc704) | 0.60 | \uc7ac\ud604\uc728 \uc6b0\uc120 |\n\n> **sLLM \ud658\uacbd \uc8fc\uc758**: \uc704 \uae30\uc900\uc740 \uace0\uc131\ub2a5 \uc784\ubca0\ub529 \ubaa8\ub378 \uae30\uc900\uc774\ub2e4. sLLM \uc784\ubca0\ub529\uc740 \ubca1\ud130 \uacf5\uac04 \ubd84\ubcc4\ub825\uc774 \ub0ae\uc544 \uad00\ub828 \uccad\ud06c\ub3c4 \uc720\uc0ac\ub3c4\uac00 \ub0ae\uac8c \uce21\uc815\ub418\ubbc0\ub85c, \uc704 \uac12\uc744 \uadf8\ub300\ub85c \uc801\uc6a9\ud558\uba74 \uacb0\uacfc\uac00 \uac70\uc758 \ubc18\ud658\ub418\uc9c0 \uc54a\ub294\ub2e4. sLLM \ud658\uacbd\uc758 \uc2dc\uc2a4\ud15c \uae30\ubcf8\uac12\uc740 0.3\uc774\uba70, \uc704 \ud45c\ub294 \uad00\ub9ac\uc790\uac00 \uace0\uc131\ub2a5 \ubaa8\ub378 \uc804\ud658 \uc2dc \ucc38\uace0\ud558\ub294 \uc6a9\ub3c4\uc774\ub2e4.'

if old in content:
    content = content.replace(old, new)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print('Done: added sLLM context note after threshold guide table')
else:
    print('ERROR: target string not found')
