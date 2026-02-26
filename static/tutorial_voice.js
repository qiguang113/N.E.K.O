class TutorialVoice {
    constructor(manager) {
        this.manager = manager || null;
    }

    speak(text, speechKey = null) {
        if (!this.manager || typeof this.manager.speakTutorialTextDirect !== 'function') return;
        this.manager.speakTutorialTextDirect(text, speechKey);
    }

    stop() {
        if (this.manager && typeof this.manager.stopTutorialNarration === 'function') {
            this.manager.stopTutorialNarration();
        }
    }
}

window.TutorialVoice = TutorialVoice;
