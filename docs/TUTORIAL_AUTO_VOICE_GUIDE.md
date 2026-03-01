# N.E.K.O 新手引导自动语音功能使用文档

## 概述

本文档说明 N.E.K.O 新手引导系统的自动语音播放功能。该功能使用浏览器内置的 **Speech Synthesis API**，完全免费，无需网络连接，能够为每个教程步骤自动朗读标题和描述。

---

## 功能特点

### 核心特性
- ✅ **完全免费**：使用浏览器内置 API，无需任何 API Key 或付费服务
- ✅ **自动播放**：教程步骤切换时自动朗读当前步骤内容
- ✅ **智能文本处理**：自动清理不适合朗读的内容（HTML 标签、表情符号等）
- ✅ **语音队列管理**：支持多个语音按顺序播放
- ✅ **智能语音选择**：自动选择最佳中文语音（优先 Microsoft Huihui/Xiaoxiao Desktop）
- ✅ **平滑过渡**：步骤切换时自动停止前一个语音，避免重叠
- ✅ **可自定义**：支持调整语速、音调、音量
- ✅ **多浏览器兼容**：支持 Chrome、Edge、Firefox、Safari 等主流浏览器

### 语音源
使用浏览器内置的 **Speech Synthesis API**（也称为 Web Speech API）：
- 无需网络连接
- 无需 API 配置
- 完全离线可用
- 支持多种语言和语音

---

## 文件结构

```
N.E.K.O/
├── static/
│   ├── tutorial_auto_voice.js        # 新增：自动语音模块
│   └── universal-tutorial-manager.js # 修改：集成语音播放逻辑
└── templates/
    ├── index.html                   # 修改：引入语音模块
    ├── api_key_settings.html        # 修改：引入语音模块
    ├── chara_manager.html            # 修改：引入语音模块
    ├── model_manager.html           # 修改：引入语音模块
    ├── live2d_emotion_manager.html # 修改：引入语音模块
    ├── live2d_parameter_editor.html # 修改：引入语音模块
    ├── memory_browser.html          # 修改：引入语音模块
    ├── steam_workshop_manager.html   # 修改：引入语音模块
    ├── voice_clone.html             # 修改：引入语音模块
    └── vrm_emotion_manager.html    # 修改：引入语音模块
```

---

## 使用方法

### 1. 正常使用

**无需任何配置，功能已自动集成！**

启动 N.E.K.O 后，新手引导将自动播放语音：
- 每个步骤显示时，自动朗读步骤标题和描述
- 切换到下一步时，自动停止上一个语音
- 教程结束时，自动停止所有语音并清空队列

### 2. 调整语音参数（可选）

如果你想自定义语音效果，可以在浏览器控制台中调用以下命令：

#### 查看当前语音状态
```javascript
// 在浏览器控制台中输入
window.universalTutorialManager.tutorialVoice.getStatus()
```

#### 禁用/启用语音
```javascript
// 禁用语音（停止当前播放并清空队列）
window.universalTutorialManager.tutorialVoice.setEnabled(false)

// 启用语音
window.universalTutorialManager.tutorialVoice.setEnabled(true)
```

#### 调整语速（0.1 - 10）
```javascript
// 默认 1.0（正常速度）
// 0.5 = 慢速
// 2.0 = 快速
window.universalTutorialManager.tutorialVoice.setRate(1.0)
```

#### 调整音调（0 - 2）
```javascript
// 默认 1.0（正常音调）
// 0.5 = 低音调
// 1.5 = 高音调
window.universalTutorialManager.tutorialVoice.setPitch(1.0)
```

#### 调整音量（0 - 1）
```javascript
// 默认 1.0（100% 音量）
// 0.5 = 50% 音量
window.universalTutorialManager.tutorialVoice.setVolume(1.0)
```

#### 手动选择语音
```javascript
// 查看所有可用语音
const voices = window.universalTutorialManager.tutorialVoice.getVoices();
console.table(voices.map(v => ({
    name: v.name,
    lang: v.lang,
    localService: v.localService
})));

// 手动选择某个语音
const selectedVoice = voices[0];  // 选择第一个语音
window.universalTutorialManager.tutorialVoice.setVoice(selectedVoice);
```

#### 手动播放文本
```javascript
// 立即播放指定文本
window.universalTutorialManager.tutorialVoice.speak('这是一段测试语音');

// 添加到播放队列
window.universalTutorialManager.tutorialVoice.enqueue('第一段文本');
window.universalTutorialManager.tutorialVoice.enqueue('第二段文本');
window.universalTutorialManager.tutorialVoice.enqueue('第三段文本');

// 停止播放
window.universalTutorialManager.tutorialVoice.stop();

// 暂停播放
window.universalTutorialManager.tutorialVoice.pause();

// 恢复播放
window.universalTutorialManager.tutorialVoice.resume();
```

### 3. 查看日志

语音播放的日志会在浏览器控制台中输出，前缀为 `[TutorialVoice]`：

```
[TutorialVoice] 语音模块已初始化
[TutorialVoice] 找到 5 个可用语音
[TutorialVoice] 选择语音: Microsoft Huihui Desktop
[TutorialVoice] 播放步骤语音: 欢迎来到 N.E.K.O...
[TutorialVoice] 切换步骤，停止当前语音
[TutorialVoice] 开始播放
[TutorialVoice] 播放完成
```

---

## 技术实现细节

### TutorialAutoVoice 类

位于 `static/tutorial_auto_voice.js`，提供以下核心功能：

#### 主要方法

| 方法 | 说明 |
|-----|------|
| `speak(text, options)` | 播放指定文本，支持自定义选项 |
| `enqueue(text, options)` | 将文本添加到播放队列 |
| `stop()` | 停止当前播放 |
| `pause()` | 暂停播放 |
| `resume()` | 恢复播放 |
| `setEnabled(enabled)` | 启用/禁用语音 |
| `setRate(rate)` | 设置语速 |
| `setPitch(pitch)` | 设置音调 |
| `setVolume(volume)` | 设置音量 |
| `setVoice(voice)` | 手动选择语音 |
| `getStatus()` | 获取当前状态 |
| `destroy()` | 销毁语音合成器 |

#### 自动语音选择

语音模块会自动按以下优先级选择语音：

1. **Microsoft Huihui Desktop** - 中文女声，质量最佳
2. **Microsoft Xiaoxiao Desktop** - 中文女声，年轻甜美
3. 其他中文语音
4. 任意可用语音

#### 文本清理

自动清理不适合朗读的内容：
- 移除 HTML 标签
- 移除多余的表情符号和图标
- 保留常见标点符号和数字
- 将 "N.E.K.O" 替换为 "恩艾科"（更易读）

### 集成逻辑

在 `universal-tutorial-manager.js` 中的集成点：

1. **教程开始时**：
   - 初始化 TutorialAutoVoice 实例
   - 如果模块未定义，输出警告但继续运行

2. **步骤高亮时**：
   - 自动朗读步骤标题和描述
   - 格式：`{标题}。{描述}`

3. **步骤切换时**：
   - 停止前一个语音
   - 开始播放新步骤的语音

4. **教程结束时**：
   - 停止所有语音播放
   - 清空播放队列

---

## 常见问题

### 1. 语音不播放？

**可能原因和解决方案：**

| 问题 | 解决方案 |
|------|---------|
| 浏览器不支持 Speech Synthesis API | 升级到最新版本的主流浏览器（Chrome、Edge、Firefox、Safari） |
| 语音队列太长 | 使用 `setRate()` 提高语速，或手动停止部分语音 |
| 语音不自然 | 使用 `setPitch()` 或 `setRate()` 微调参数 |
| 无法听到声音 | 检查系统音量设置和浏览器标签页的音量控制 |

### 2. 如何完全禁用语音？

在浏览器控制台中执行：
```javascript
window.universalTutorialManager.tutorialVoice.setEnabled(false)
```

这会立即停止当前播放并禁用自动语音功能。

### 3. 如何重新启用语音？

在浏览器控制台中执行：
```javascript
window.universalTutorialManager.tutorialVoice.setEnabled(true)
```

### 4. 如何让语音更快？

在浏览器控制台中执行：
```javascript
// 设置为 2 倍速（最大推荐值）
window.universalTutorialManager.tutorialVoice.setRate(2.0)

// 如果觉得太快，可以调回 1.5 或 1.2
window.universalTutorialManager.tutorialVoice.setRate(1.5)
```

### 5. 语音不完整？

某些步骤的文本可能较长，浏览器会自动截断。这是正常的。

如果希望完整播放，可以：
1. 在教程文本中添加更简短的描述
2. 修改 `static/tutorial_auto_voice.js` 中的文本处理逻辑

---

## 浏览器兼容性

| 浏览器 | Speech Synthesis 支持 |
|---------|---------------------|
| Chrome 71+ | ✅ 完全支持 |
| Edge 14+ | ✅ 完全支持 |
| Firefox 62+ | ✅ 完全支持 |
| Safari 7+ | ✅ 完全支持（macOS、iOS）|
| Opera 33+ | ✅ 完全支持 |
| IE 11 | ❌ 不支持 |

**推荐浏览器**：Chrome、Edge、Firefox、Safari

---

## 优势说明

### 与其他 TTS 方案对比

| 特性 | 浏览器 Speech Synthesis | 阶跃星辰 | GPT-SoVITS | CosyVoice |
|-----|---------------------|----------|------------|-----------|
| 费用 | ✅ 完全免费 | 免费（可能有限制）| 需要自建 | 需要自建 |
| 配置复杂度 | ✅ 零配置 | 需要网络连接 | 需要模型文件 | 需要模型文件 |
| 网络依赖 | ❌ 无依赖 | 需要稳定网络 | 无 | 无 |
| 离线可用 | ✅ 完全离线 | ❌ 需要在线 | ❌ 需要在线 | ❌ 需要在线 |
| 音质 | ⭐⭐⭐ 适中 | ⭐⭐⭐ 优秀 | ⭐⭐⭐⭐⭐ 优秀 | ⭐⭐⭐⭐⭐ 优秀 |
| 兼容性 | ✅ 主流浏览器 | WebSocket 兼容 | WebSocket 兼容 | WebSocket 兼容 |

---

## 开发者指南

### 扩展或修改功能

如果需要修改语音功能，主要关注以下文件：

1. **`static/tutorial_auto_voice.js`** - 语音模块核心
   - 修改语音选择优先级
   - 调整文本清理逻辑
   - 添加更多语音控制选项

2. **`static/universal-tutorial-manager.js`** - 教程管理器
   - 修改语音触发时机
   - 添加语音回调函数
   - 集成到其他教程步骤

### 添加新的语音服务

如需使用其他 TTS 服务，可以修改 `TutorialAutoVoice` 类：

```javascript
// 示例：添加新的 speak 方法
async speakWithCustomTTS(text) {
    // 调用外部 TTS API
    const audioUrl = await this._fetchCustomTTSAudio(text);

    // 使用 Audio 对象播放
    const audio = new Audio(audioUrl);
    audio.play();

    // 等待播放结束
    return new Promise(resolve => {
        audio.onended = () => resolve();
    });
}
```

---

## 总结

新手引导自动语音功能已完全集成到 N.E.K.O 项目中：

✅ 使用浏览器内置 Speech Synthesis API，完全免费
✅ 自动为每个教程步骤播放标题和描述
✅ 智能文本处理，清理不适合朗读的内容
✅ 步骤切换时自动停止前一个语音
✅ 教程结束时清理所有语音
✅ 支持自定义语音参数
✅ 无需任何配置，开箱即用

---

**注意**：首次使用时，请确保允许浏览器播放音频。如果浏览器阻止自动播放，请点击页面任意位置后重试。
