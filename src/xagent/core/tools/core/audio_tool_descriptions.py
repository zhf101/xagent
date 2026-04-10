"""
Audio tool descriptions

This module contains the description templates for audio processing tools.
Extracted from audio_tool.py for better maintainability.
"""

# Description for transcribe_audio tool
TRANSCRIBE_AUDIO_DESCRIPTION = """
使用 Speech-to-Text (ASR) 将音频转写成文本。

这个工具会把音频文件里的口语内容转换为书面文本。
支持多语言，并且可以返回更细的时间戳信息。

可用模型（⭐[DEFAULT] 表示当前配置的默认模型）：
{}

**重要：优先使用标记为 ⭐[DEFAULT] 的默认模型。只有当用户明确要求其他模型时，才填写 model_id。**

参数：
- audio_file_path（必填）：要转写的音频文件路径、file_id 或 URL
- language（可选）：语言代码，例如 'zh'、'en'、'yue'、'ja'、'ko'
- model_id（可选）：指定使用的 ASR 模型；留空则使用 ⭐[DEFAULT]
- verbose（可选）：如果需要返回分段细节，设为 True；默认 False

语言支持：
- 'zh'：中文普通话
- 'en'：英文
- 'yue'：粤语
- 'ja'：日语
- 'ko'：韩语
- 以及模型能力允许的更多语言

支持的音频格式：wav、mp3、m4a、flac、ogg 等常见格式

高级能力（取决于模型是否支持）：
- Speaker diarization：区分不同说话人
- Timestamps：返回词级或片段级时间信息
- Confidence scores：返回转写置信度
- Smart segment merging：相邻且属于同一说话人的片段会自动合并（间隔 < 1 秒），提升可读性

输出：
- file_id：workspace 中完整转写 JSON 文件的 File ID
- transcription_path：保存的转写 JSON 文件路径
- saved_to_workspace：是否已保存到 workspace
- segments：详细分段信息（仅在 verbose=True 时出现）
- language：识别出的语言代码
- model_used：实际使用的模型
- text_length：转写文本长度
- segment_count：分段数量

提示：如果要读取完整转写文本，请使用 read_file(file_id)。

JSON 输出格式（保存到 file_id 对应文件中）：
```json
{{
  "model": "model_name",
  "language": "zh",
  "text": "Full transcribed text here...",
  "segments": [
    {{
      "text": "Segment text",
      "start": 0.0,
      "end": 2.5,
      "speaker": "spk1",
      "confidence": 0.95
    }}
  ],
  "metadata": {{
    "audio_source": "input_audio.mp3",
    "verbose_mode": true,
    "total_segments": 10
  }}
}}
```

提示：相邻且属于同一说话人的片段会自动合并（间隔小于 1 秒），以提升可读性并减少碎片化。
""".strip()

# Description for synthesize_speech tool
SYNTHESIZE_SPEECH_DESCRIPTION = """
使用 Text-to-Speech (TTS) 把文本合成为语音。

这个工具会把书面文本转换为自然语音音频。
支持多种 voice、语言和音频格式。

可用模型（⭐[DEFAULT] 表示当前配置的默认模型）：
{}

**重要：优先使用标记为 ⭐[DEFAULT] 的默认模型。只有当用户明确要求其他模型时，才填写 model_id。**

参数：
- text（必填）：要合成为语音的文本内容
- voice（可选）：voice ID 或名称，例如 'zh-android'、'zh-female'、'en-male'；留空则使用默认 voice
- language（可选）：语言代码，例如 'zh'、'en'、'yue'；如果不填，部分模型会自动识别
- format（可选）：输出音频格式，例如 'mp3'、'wav'、'pcm'；默认 'mp3'
- model_id（可选）：指定使用的 TTS 模型；留空则使用 ⭐[DEFAULT]
- reference_audio（可选）：用于 voice cloning 的参考音频路径（前提是模型支持）

voice 能力取决于模型：
- 大多数模型支持标准 voice，例如 male、female、neutral
- 部分模型支持基于 reference_audio 的 voice cloning
- 多语言模型可能会根据文本自动判断语言

音频格式说明：
- mp3：压缩格式，适合语音场景（默认）
- wav：无压缩格式，质量更高
- pcm：原始音频数据

生成的音频文件会自动保存到 workspace。
""".strip()

# Description for synthesize_speech_json tool
SYNTHESIZE_SPEECH_JSON_DESCRIPTION = """
使用 Text-to-Speech (TTS) 按 JSON 结构批量合成语音。

这个工具可以在一次调用里把多个文本片段生成对应的语音文件。
支持灵活的 JSON 字段映射、voice cloning 和批量处理。

可用模型（⭐[DEFAULT] 表示当前配置的默认模型）：
{}

**重要：优先使用标记为 ⭐[DEFAULT] 的默认模型。只有当用户明确要求其他模型时，才填写 model_id。**

参数：
- json_data（可选）：包含合成配置的 JSON 字符串或 dict；json_data 和 file_id 至少提供一个
- file_id（可选）：读取 JSON 数据用的 File ID、文件路径或 URL；json_data 和 file_id 至少提供一个
- segments_field（可选）：存放 segments 数组的字段名，默认 "segments"
- text_field（可选）：每个 segment 内文本字段名，默认 "text"
- voice_field（可选）：每个 segment 内 voice 字段名，默认 "voice"
- reference_field（可选）：每个 segment 内参考音频字段名，默认 "reference_audio"
- default_voice（可选）：当 segment 未指定 voice 时使用的默认 voice
- default_language（可选）：默认语言代码；为 None 时自动检测
- format（可选）：输出音频格式，默认 'mp3'
- sample_rate（可选）：采样率（Hz），默认由模型决定
- model_id（可选）：指定使用的 TTS 模型；留空则使用 ⭐[DEFAULT]
- batch_size（可选）：并行处理数量（1-20，默认 5）

JSON 格式示例（嵌套 segment 结构）：
```json
{{
    "segments": [
        {{"text": "你好世界", "voice": "zh-female", "reference_audio": "ref_voice_1"}},
        {{"text": "这是一个测试", "voice": "zh-male", "reference_audio": "ref_voice_2"}}
    ],
    "default_voice": "zh-female",
    "output_format": "mp3",
    "sample_rate": 24000
}}
```

Voice Cloning：
- 可在每个 segment 中使用 reference_audio，基于参考音频复制 voice
- 同时支持 workspace file_id 和直接文件路径（绝对/相对路径）
- voice cloning 质量与参考音频质量强相关
- 不是所有模型都支持 voice cloning

批处理说明：
- 所有 segment 会并行处理，以提升效率
- 可通过 batch_size 控制并发度（1-20）
- 合成期间会显示进度
- 单个 segment 失败不会阻断整批处理

输出：
- success（bool）：是否全部合成成功
- results（list）：每个 segment 对应的合成结果
- total（int）：处理的 segment 总数
- successful（int）：成功数量
- failed（int）：失败数量
- errors（list）：失败 segment 的错误信息列表
- saved_to_workspace（bool）：音频文件是否已保存到 workspace

对于涉及文件链路的 workflow，建议优先使用 file_id。
file_id 支持：File ID、文件路径或 URL。
""".strip()
