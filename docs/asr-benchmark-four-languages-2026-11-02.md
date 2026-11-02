# 中英日韩限定语种 A/B 复测（2026-11-02）

## 测试配置

- 版本 A：多语种 ASR 不设置 ln，候选覆盖全部语言。
- 版本 B：多语种 ASR 设置 `ln=zh|en|ja|ko`；中文方言 ASR 与自动选择算法均不变。
- 两版使用同一组 FLEURS/KeSpeech 公开原声：14 段，合计 147.43 秒。每段录音同时送入多语种及方言模型。
- 四语种组合超过讯飞建议的三种上限；本轮实际连接与识别成功，但仍需评估更多场景。

## 结论

- 两版 14/14 均成功调用双路。目标范围内的 9 段（粤语 2、普通话 1、英语 1、日语 1、韩语 1、成都/郑州/青岛话 3）语言/路由正确率由 7/9 提升为 9/9。
- 两段粤语从 vi → zh，转为采用方言模型，输出可理解的中文。第二段粤语虽然显著改善，仍有文字错误与结尾缺字。
- 中英日韩和成都/郑州/青岛话等另外 7 段，原有识别质量保持稳定。
- 法、西、德、俄、越这 5 段处于新配置的支持范围外，全部被判为 en，识别明显下降。其劣化是缩小候选语言范围的边界效应。
- 样本量有限，不能将 9/9 等同于总体语言识别率或方言覆盖率。

## 语种和最终模型对照

| 语音 | A: 自动语言 | B: 自动语言 | A: 最终模型 | B: 最终模型 |
|---|---|---|---|---|
| 粤语 / yue_hant_hk_0000 | vi | zh | multilingual | dialect |
| 粤语 / yue_hant_hk_0001 | vi | zh | multilingual | dialect |
| 普通话 / cmn_hans_cn_0000 | zh | zh | dialect | dialect |
| 英语 / en_us_0000 | en | en | multilingual | multilingual |
| 法语 / fr_fr_0000 | fr | en | multilingual | multilingual |
| 日语 / ja_jp_0000 | ja | ja | multilingual | multilingual |
| 西班牙语 / es_419_0000 | fr | en | multilingual | multilingual |
| 韩语 / ko_kr_0000 | ko | ko | multilingual | multilingual |
| 德语 / de_de_0000 | de | en | multilingual | multilingual |
| 俄语 / ru_ru_0000 | ru | en | multilingual | multilingual |
| 越南语 / vi_vn_0000 | vi | en | multilingual | multilingual |
| 成都话 / chengdu | zh | zh | dialect | dialect |
| 郑州话 / zhengzhou | zh | zh | dialect | dialect |
| 青岛话 / qingdao | zh | zh | dialect | dialect |

## 原文与实际结果

### 粤语（yue_hant_hk_0000）
- 参考文本：在 短 短 兩 週 內 美 軍 和 自 由 法 國 軍 就 解 放 了 南 法 並 轉 向 德 國
- A 最终：Cho tuyến tuyến đón cháu nội mấy quán quà chiều và quà quán chào gái phòng liều lạm phát bình chuyển hàng đặt cọc.
- B 最终：在短短两周内，美军和自由法国军就解放了南法，并转向德国。
- B 方言模型：在短短两周内，美军和自由法国军就解放了南法，并转向德国。
- 音频：https://huggingface.co/datasets/FluidInference/fleurs-full/resolve/main/yue_hant_hk/yue_hant_hk_0000.wav

### 粤语（yue_hant_hk_0001）
- 参考文本：奧 利 佛 ‧薩 克 斯 在 他 的 文 章 〈總 統 的 演 講 〉中 指 出 因 為 腦 部 受 損 而 無 法 理 解 演 講 內 容 的 人 仍 然 可 以 準 確 感 受 到 演 講 者 的 誠 意
- A 最终：Ô nệ phật sát hát, sĩ trọng tha thiết mạnh trong trong thống đức dân cộng dân. Chỉ trước nhân văn nô bổ xảo suối nhì mộ phạt lễ cá dân cộng đồng tiếng Nhật, gần như hơi trốn khỏi cảm xúc của dân cộng dân tiếp theo.
- B 最终：奥尼弗萨克斯在他的文章，总统的演讲中指出，因为脑部受损而无法理解演讲内容的人，仍然可以准确感受到演者。
- B 方言模型：奥尼弗萨克斯在他的文章，总统的演讲中指出，因为脑部受损而无法理解演讲内容的人，仍然可以准确感受到演者。
- 音频：https://huggingface.co/datasets/FluidInference/fleurs-full/resolve/main/yue_hant_hk/yue_hant_hk_0001.wav

### 普通话（cmn_hans_cn_0000）
- 参考文本：这 并 不 是 告 别 这 是 一 个 篇 章 的 结 束 也 是 新 篇 章 的 开 始
- A 最终：这并不是告别，这是一个篇章的结束，也是新篇章的开始。
- B 最终：这并不是告别，这是一个篇章的结束，也是新篇章的开始。
- B 方言模型：这并不是告别，这是一个篇章的结束，也是新篇章的开始。
- 音频：https://huggingface.co/datasets/FluidInference/fleurs-full/resolve/main/cmn_hans_cn/cmn_hans_cn_0000.wav

### 英语（en_us_0000）
- 参考文本：however due to the slow communication channels styles in the west could lag behind by 25 to 30 year
- A 最终：However, due to the slow communication channels styles in the west could lag behind by 25 to 30 years.
- B 最终：However, due to the slow communication channels styles in the west could lag behind by 25 to 30 years.
- B 方言模型：However due to the slow communication channels styles in the west could lag behind by 25 to 30 years.
- 音频：https://huggingface.co/datasets/FluidInference/fleurs-full/resolve/main/en_us/en_us_0000.wav

### 法语（fr_fr_0000）
- 参考文本：l'accident a eu lieu en terrain montagneux et il semblerait que cela ait été causé par un incendie malveillant
- A 最终：L'accident a eu lieu en terrain montagneux. Et il semblerait que cela ait été causé par un incendie malveillant.
- B 最终：L'accident a eu lieu en terrain montagneux. It semblerait que cela ait étécauséPAR un incendie malveillant.
- B 方言模型：Laxedon AustraliaMontana.
- 音频：https://huggingface.co/datasets/FluidInference/fleurs-full/resolve/main/fr_fr/fr_fr_0000.wav

### 日语（ja_jp_0000）
- 参考文本：インターネットで 敵対的環境コース について検索すると おそらく現地企業の住所が出てくるでしょう
- A 最终：インターネットで敵対的環境コースについて検索すると、おそらく現地企業の住所が出てくるでしょう。
- B 最终：インターネットで敵対的環境コースについて検索すると、おそらく現地企業の住所が出てくるでしょう。
- B 方言模型：Internet today take care of course and it can actually多我是那个跟gd有哪些修改的说。
- 音频：https://huggingface.co/datasets/FluidInference/fleurs-full/resolve/main/ja_jp/ja_jp_0000.wav

### 西班牙语（es_419_0000）
- 参考文本：se recomienda enfáticamente a los viajeros que se informen sobre cualquier riesgo de clima extremo en el área que visitan dado que ello puede afectar sus planes de viaje
- A 最终：Oui. Se recomienda enfáticamente a los viajeros que se informen sobre cualquier riesgo del clima extremo en el área que visitan dado que ello puede afectar sus planes de viaje
- B 最终：Yes. So uhm, uh
- B 方言模型：Sarahkaminaemphatic a mental of yahirokis informantcerebral Carrie hotelclimaxtremo anEliakevistonallocation of perfectors who planted the vehicle.
- 音频：https://huggingface.co/datasets/FluidInference/fleurs-full/resolve/main/es_419/es_419_0000.wav

### 韩语（ko_kr_0000）
- 参考文本：다리 밑 수직 간격은 15미터이며 공사는 2011년 8월에 마무리되었으며 해당 다리의 통행금지는 2017년 3월까지이다
- A 最终：다리미 수직 간격은 15m이며 공사는 2011년 8월에 마무리되었으며, 해당 다리의 통행금지는 2017년 3월까지이다.
- B 最终：다리미 수직 간격은 15m이며 공사는 2011년 8월에 마무리되었으며, 해당 다리의 통행금지는 2017년 3월까지이다.
- B 方言模型：塔利米斯基共和国18米代庙共产人1400元拍落的8亩地的寺庙。
- 音频：https://huggingface.co/datasets/FluidInference/fleurs-full/resolve/main/ko_kr/ko_kr_0000.wav

### 德语（de_de_0000）
- 参考文本：für die besten aussichten auf hongkong sollten sie die insel verlassen und zum gegenüberliegenden ufer von kowloon fahren
- A 最终：Für die besten Aussichten auf Hongkong sollten Sie die Insel verlassen und zum gegenüberliegenden Ufer von Kowloon fahren.
- B 最终：For die besten Aussichten auf Hongkong sollten Sie die Insel verlassen und zum gegenüberliegenden Ufer von Kowloon fahren.
- B 方言模型：For the best and all system ofhong kong Walton city in the falcon on sung Gigi newBerlin in theUber phone covalon Faron.
- 音频：https://huggingface.co/datasets/FluidInference/fleurs-full/resolve/main/de_de/de_de_0000.wav

### 俄语（ru_ru_0000）
- 参考文本：в древнем китае использовали уникальный способ обозначения периодов времени каждый этап китая или каждая семья находившаяся у власти были особой династией
- A 最终：В Древнем Китае использовали уникальный способ обозначения периодов времени. Каждый этап Китая или каждая семья. Находившиеся у власти, были особой династией.
- B 最终：In the ancient Ketai, they used a unique way to define periods of time. каждыйэтапКитаяиликаждаясемья находившиесяувласти, былиособойдинастией.
- B 方言模型：
- 音频：https://huggingface.co/datasets/FluidInference/fleurs-full/resolve/main/ru_ru/ru_ru_0000.wav

### 越南语（vi_vn_0000）
- 参考文本：văn hóa và bộ lạc cổ xưa đã bắt đầu giữ những con vật này để dễ lấy sữa tóc thịt và da
- A 最终：Văn hóa  và bộ lạc cổ xưa đã bắt đầu giữ những con vật này.  để dễ lấy sữa, tóc, thịt và da.
- B 最终：文化。 Vàbộlạc cổxưa đãbắt đầu giữnhững con vật này. đểdễlấy sữa tóc thịt vàda
- B 方言模型：万华化膜了公司的报告有人工挖泥的尹力则违约。
- 音频：https://huggingface.co/datasets/FluidInference/fleurs-full/resolve/main/vi_vn/vi_vn_0000.wav

### 成都话（chengdu）
- 参考文本：关系到整个民族的素质和道德情操的提高
- A 最终：关系到整个民族的素质和道德情操的提高。
- B 最终：关系到整个民族的素质和道德情操的提高。
- B 方言模型：关系到整个民族的素质和道德情操的提高。
- 音频：https://wen2cheng.github.io/gt/chengdu_1024426/dialect/eval/1024426_0ad360fb.wav

### 郑州话（zhengzhou）
- 参考文本：这就和她挑水果是一个道理
- A 最终：这就和他挑水果是一个道理。
- B 最终：这就和他挑水果是一个道理。
- B 方言模型：这就和他挑水果是一个道理。
- 音频：https://wen2cheng.github.io/gt/zhengzhou_1017637/dialect/eval/1017637_43dae8a6.wav

### 青岛话（qingdao）
- 参考文本：旋即不少游客询问几款电动车的售价
- A 最终：旋即不少游客询问几款电动车的售价？
- B 最终：旋即不少游客询问几款电动车的售价？
- B 方言模型：旋即不少游客询问几款电动车的售价？
- 音频：https://wen2cheng.github.io/gt/qingdao_1007609/dialect/eval/1007609_135ad4d5.wav

## 可复现文件

- 基线 JSON：`%TEMP%\xuhua-asr-eval\public-benchmark\results-all-languages-2026-11-02.json`
- 四语种 JSON：`%TEMP%\xuhua-asr-eval\public-benchmark\results-zh-en-ja-ko-2026-11-02.json`
- 录音及标注：同一 public-benchmark 目录。
- 运行器：`%TEMP%\xuhua-public-benchmark-run-four.py`。
- PC 工作区未提交、未推送 GitHub，未更新腾讯云。
