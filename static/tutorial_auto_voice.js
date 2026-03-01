/**
 * N.E.K.O 新手引导自动语音模块
 * 使用浏览器内置的 speechSynthesis API（完全免费，无需网络）
 */

class TutorialAutoVoice {
    constructor() {
        this.synth = window.speechSynthesis;
        this.currentUtterance = null;
        this.voices = [];
        this.selectedVoice = null;
        this.isSpeaking = false;
        this.queue = [];
        this.isPaused = false;

        // 配置
        this.enabled = true;
        this.rate = 1.0;      // 语速 (0.1 - 10)
        this.pitch = 1.0;     // 音调 (0 - 2)
        this.volume = 1.0;    // 音量 (0 - 1)

        // 事件回调
        this.onStart = null;
        this.onEnd = null;
        this.onError = null;

        this._init();
    }

    /**
     * 初始化语音合成器
     */
    _init() {
        if (!this.synth) {
            console.warn('[TutorialVoice] 浏览器不支持 speechSynthesis API');
            return;
        }

        // 加载可用语音列表
        this._loadVoices();

        // 监听语音变化
        if (this.synth.onvoiceschanged !== undefined) {
            this.synth.onvoiceschanged = () => {
                console.log('[TutorialVoice] 语音列表已更新');
                this._loadVoices();
            };
        }
    }

    /**
     * 加载可用语音列表
     */
    _loadVoices() {
        this.voices = this.synth.getVoices() || [];
        console.log(`[TutorialVoice] 找到 ${this.voices.length} 个可用语音`);

        // 自动选择中文语音
        this._selectBestVoice();
    }

    /**
     * 自动选择最佳语音（优先中文女声）
     */
    _selectBestVoice() {
        if (this.voices.length === 0) {
            console.warn('[TutorialVoice] 没有可用语音');
            this.selectedVoice = null;
            return;
        }

        // 优先级：
        // 1. Microsoft Huihui Desktop (中文女声，质量最好)
        // 2. Microsoft Xiaoxiao Desktop (中文女声，年轻甜美)
        // 3. 其他中文语音
        // 4. 任意语音

        const priorities = [
            'Microsoft Huihui Desktop',
            'Microsoft Xiaoxiao Desktop',
            'Google 普通话',
            'Google 粤通话',
            'Huihui',
            'Xiaoxiao'
        ];

        for (const priority of priorities) {
            const voice = this.voices.find(v =>
                v.name.includes(priority) || v.name === priority
            );
            if (voice) {
                this.selectedVoice = voice;
                console.log(`[TutorialVoice] 选择语音: ${voice.name}`);
                return;
            }
        }

        // 如果没有找到优先语音，选择第一个中文语音
        const chineseVoice = this.voices.find(v =>
            v.lang && (v.lang.startsWith('zh') || v.lang.startsWith('cmn'))
        );

        this.selectedVoice = chineseVoice || this.voices[0];
        console.log(`[TutorialVoice] 最终语音: ${this.selectedVoice?.name || '默认'}`);
    }

    /**
     * 检查语音合成器是否可用
     */
    isAvailable() {
        return !!this.synth;
    }

    /**
     * 检查是否正在播放
     */
    checkSpeaking() {
        return this.isSpeaking;
    }

    /**
     * 播放文本
     * @param {string} text - 要朗读的文本
     * @param {Object} options - 播放选项
     */
    speak(text, options = {}) {
        if (!this.enabled) {
            console.log('[TutorialVoice] 语音已禁用');
            return;
        }

        if (!this.synth) {
            console.warn('[TutorialVoice] 语音合成器不可用');
            return;
        }

        // 清理文本（移除HTML标签、表情符号等）
        const cleanText = this._cleanText(text);

        if (!cleanText || cleanText.trim().length === 0) {
            console.log('[TutorialVoice] 文本为空，跳过播放');
            return;
        }

        // 应用选项
        const rate = options.rate ?? this.rate;
        const pitch = options.pitch ?? this.pitch;
        const volume = options.volume ?? this.volume;
        const voice = options.voice ?? this.selectedVoice;

        console.log(`[TutorialVoice] 准备播放: "${cleanText.substring(0, 30)}..."`);

        // 创建语音对象
        const utterance = new SpeechSynthesisUtterance(cleanText);
        utterance.voice = voice;
        utterance.rate = rate;
        utterance.pitch = pitch;
        utterance.volume = volume;

        // 设置语言（从语音自动获取）
        if (voice && voice.lang) {
            utterance.lang = voice.lang;
        }

        // 设置事件回调
        utterance.onstart = () => {
            this.isSpeaking = true;
            console.log('[TutorialVoice] 开始播放');
            if (typeof this.onStart === 'function') {
                this.onStart();
            }
        };

        utterance.onend = () => {
            this.isSpeaking = false;
            this.currentUtterance = null;
            console.log('[TutorialVoice] 播放完成');
            if (typeof this.onEnd === 'function') {
                this.onEnd();
            }
            // 播放下一个队列项
            this._playNext();
        };

        utterance.onerror = (event) => {
            this.isSpeaking = false;
            this.currentUtterance = null;
            console.error('[TutorialVoice] 播放错误:', event);
            if (typeof this.onError === 'function') {
                this.onError(event);
            }
            // 播放下一个队列项
            this._playNext();
        };

        // 停止当前播放
        this.stop();

        // 保存当前语音对象
        this.currentUtterance = utterance;

        // 立即播放
        this.synth.speak(utterance);
    }

    /**
     * 添加文本到播放队列
     * @param {string} text - 要朗读的文本
     * @param {Object} options - 播放选项
     */
    enqueue(text, options = {}) {
        const cleanText = this._cleanText(text);
        if (!cleanText || cleanText.trim().length === 0) {
            return;
        }

        this.queue.push({ text: cleanText, options });
        console.log(`[TutorialVoice] 添加到队列: "${cleanText.substring(0, 30)}..." (队列: ${this.queue.length})`);

        // 如果当前没有在播放，立即播放
        if (!this.isSpeaking && this.queue.length === 1) {
            this._playNext();
        }
    }

    /**
     * 清空播放队列
     */
    clearQueue() {
        this.queue = [];
        console.log('[TutorialVoice] 清空播放队列');
    }

    /**
     * 播放队列中的下一个
     */
    _playNext() {
        if (this.queue.length === 0) {
            return;
        }

        const next = this.queue.shift();
        this.speak(next.text, next.options);
    }

    /**
     * 停止当前播放
     */
    stop() {
        if (this.synth) {
            this.synth.cancel();
        }
        this.isSpeaking = false;
        this.currentUtterance = null;
    }

    /**
     * 暂停播放
     */
    pause() {
        if (this.synth && this.isSpeaking) {
            this.synth.pause();
            this.isPaused = true;
            console.log('[TutorialVoice] 暂停播放');
        }
    }

    /**
     * 恢复播放
     */
    resume() {
        if (this.synth && this.isPaused) {
            this.synth.resume();
            this.isPaused = false;
            console.log('[TutorialVoice] 恢复播放');
        }
    }

    /**
     * 启用/禁用语音
     * @param {boolean} enabled - 是否启用
     */
    setEnabled(enabled) {
        this.enabled = enabled;
        console.log(`[TutorialVoice] 语音${enabled ? '已启用' : '已禁用'}`);

        if (!enabled) {
            this.stop();
        }
    }

    /**
     * 设置语速 (0.1 - 10)
     * @param {number} rate - 语速
     */
    setRate(rate) {
        this.rate = Math.max(0.1, Math.min(10, rate));
        console.log(`[TutorialVoice] 语速: ${this.rate}`);
    }

    /**
     * 设置音调 (0 - 2)
     * @param {number} pitch - 音调
     */
    setPitch(pitch) {
        this.pitch = Math.max(0, Math.min(2, pitch));
        console.log(`[TutorialVoice] 音调: ${this.pitch}`);
    }

    /**
     * 设置音量 (0 - 1)
     * @param {number} volume - 音量
     */
    setVolume(volume) {
        this.volume = Math.max(0, Math.min(1, volume));
        console.log(`[TutorialVoice] 音量: ${this.volume}`);
    }

    /**
     * 手动选择语音
     * @param {SpeechSynthesisVoice} voice - 要使用的语音
     */
    setVoice(voice) {
        if (this.voices.includes(voice)) {
            this.selectedVoice = voice;
            console.log(`[TutorialVoice] 手动选择语音: ${voice.name}`);
        }
    }

    /**
     * 获取可用语音列表
     */
    getVoices() {
        return this.voices;
    }

    /**
     * 获取当前选择的语音
     */
    getSelectedVoice() {
        return this.selectedVoice;
    }

    /**
     * 获取语音状态
     */
    getStatus() {
        return {
            isAvailable: !!this.synth,
            isEnabled: this.enabled,
            isSpeaking: this.isSpeaking,
            isPaused: this.isPaused,
            queueLength: this.queue.length,
            voiceName: this.selectedVoice?.name || '默认',
            rate: this.rate,
            pitch: this.pitch,
            volume: this.volume
        };
    }

    /**
     * 清理文本（移除不适合朗读的内容）
     * @param {string} text - 原始文本
     * @returns {string} 清理后的文本
     */
    _cleanText(text) {
        if (typeof text !== 'string') {
            text = String(text);
        }

        let cleaned = text;

        // 移除 HTML 标签
        cleaned = cleaned.replace(/<[^>]*>/g, '');

        // 移除多余的表情符号和图标
        cleaned = cleaned.replace(/[^\w\s\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/g, (match) => {
            // 保留常见标点符号和数字
            if (/^[，。！？、，；：""''（）【】\d\s]+$/.test(match)) {
                return match;
            }
            return ' ';
        });

        // 将 N.E.K.O 替换为易读的 "恩艾科"
        cleaned = cleaned.replace(/N\s*\.?\s*E\s*\.?\s*K\s*\.?\s*O\s*\.?/gi, '恩艾科');

        // 规范化空格
        cleaned = cleaned.replace(/\s+/g, ' ').trim();

        return cleaned;
    }

    /**
     * 销毁语音合成器（释放资源）
     */
    destroy() {
        this.stop();
        this.clearQueue();
        this.currentUtterance = null;
        this.selectedVoice = null;
        this.voices = [];
        console.log('[TutorialVoice] 语音模块已销毁');
    }
}

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TutorialAutoVoice;
}
