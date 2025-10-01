(function() {
    // Prevent multiple instances
    if (window.AIAssistantWidget) {
        return;
    }

    class AIAssistantWidget {
        constructor() {
            this.isOpen = false;
            this.sessionId = this.generateSessionId();
            this.apiUrl = '/api/chat';// Change this for production
            this.messages = [];
            
            this.init();
        }
        
        generateSessionId() {
            return 'session_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();
        }
        
        init() {
            this.createStyles();
            this.createWidget();
            this.attachEventListeners();
        }
        
        createStyles() {
            const style = document.createElement('style');
            style.textContent = `
                .ai-widget-container {
                    position: fixed;
                    bottom: 20px;
                    right: 20px;
                    z-index: 10000;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                }
                
                .ai-widget-button {
                    width: 60px;
                    height: 60px;
                    border-radius: 50%;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    border: none;
                    cursor: pointer;
                    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: white;
                    font-size: 24px;
                    transition: all 0.3s ease;
                }
                
                .ai-widget-button:hover {
                    transform: scale(1.1);
                    box-shadow: 0 6px 30px rgba(0, 0, 0, 0.4);
                }
                
                .ai-widget-chat {
                    position: absolute;
                    bottom: 80px;
                    right: 0;
                    width: 350px;
                    height: 500px;
                    background: white;
                    border-radius: 12px;
                    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
                    display: none;
                    flex-direction: column;
                    overflow: hidden;
                }
                
                .ai-widget-header {
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 16px;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }
                
                .ai-widget-title {
                    font-size: 16px;
                    font-weight: 600;
                }
                
                .ai-widget-close {
                    background: none;
                    border: none;
                    color: white;
                    cursor: pointer;
                    font-size: 18px;
                    padding: 0;
                    width: 24px;
                    height: 24px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }
                
                .ai-widget-messages {
                    flex: 1;
                    overflow-y: auto;
                    padding: 16px;
                    background: #f8f9fa;
                }
                
                .ai-widget-message {
                    margin-bottom: 12px;
                    display: flex;
                    align-items: flex-start;
                }
                
                .ai-widget-message.user {
                    justify-content: flex-end;
                }
                
                .ai-widget-message-content {
                    max-width: 80%;
                    padding: 12px 16px;
                    border-radius: 18px;
                    word-wrap: break-word;
                }
                
                .ai-widget-message.user .ai-widget-message-content {
                    background: #667eea;
                    color: white;
                }
                
                .ai-widget-message.assistant .ai-widget-message-content {
                    background: white;
                    color: #333;
                    border: 1px solid #e9ecef;
                }
                
                .ai-widget-input-area {
                    padding: 16px;
                    border-top: 1px solid #e9ecef;
                    background: white;
                }
                
                .ai-widget-input-container {
                    display: flex;
                    gap: 8px;
                }
                
                .ai-widget-input {
                    flex: 1;
                    padding: 12px 16px;
                    border: 1px solid #e9ecef;
                    border-radius: 24px;
                    outline: none;
                    font-size: 14px;
                }
                
                .ai-widget-input:focus {
                    border-color: #667eea;
                }
                
                .ai-widget-send {
                    width: 40px;
                    height: 40px;
                    border: none;
                    background: #667eea;
                    color: white;
                    border-radius: 50%;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }
                
                .ai-widget-send:hover {
                    background: #5a6fd8;
                }
                
                .ai-widget-send:disabled {
                    background: #ccc;
                    cursor: not-allowed;
                }
                
                .ai-widget-typing {
                    display: none;
                    padding: 12px 16px;
                    color: #666;
                    font-style: italic;
                }
                
                .ai-widget-sources {
                    margin-top: 8px;
                    font-size: 12px;
                    color: #666;
                }
                
                .ai-widget-source {
                    display: block;
                    color: #667eea;
                    text-decoration: none;
                    margin-bottom: 4px;
                }
                
                .ai-widget-source:hover {
                    text-decoration: underline;
                }
                
                @media (max-width: 480px) {
                    .ai-widget-chat {
                        width: calc(100vw - 40px);
                        height: calc(100vh - 100px);
                        bottom: 80px;
                        right: 20px;
                    }
                }
            `;
            
            document.head.appendChild(style);
        }
        
        createWidget() {
            const container = document.createElement('div');
            container.className = 'ai-widget-container';
            
            container.innerHTML = `
                <button class="ai-widget-button" id="ai-widget-toggle">
                    💬
                </button>
                
                <div class="ai-widget-chat" id="ai-widget-chat">
                    <div class="ai-widget-header">
                        <div class="ai-widget-title">AI Assistant</div>
                        <button class="ai-widget-close" id="ai-widget-close">×</button>
                    </div>
                    
                    <div class="ai-widget-messages" id="ai-widget-messages">
                        <div class="ai-widget-message assistant">
                            <div class="ai-widget-message-content">
                                Hi! I'm your AI assistant. I can help you with product information, pricing, order tracking, and answer any questions about our website. How can I assist you today?
                            </div>
                        </div>
                    </div>
                    
                    <div class="ai-widget-typing" id="ai-widget-typing">
                        AI is typing...
                    </div>
                    
                    <div class="ai-widget-input-area">
                        <div class="ai-widget-input-container">
                            <input 
                                type="text" 
                                class="ai-widget-input" 
                                id="ai-widget-input" 
                                placeholder="Type your message..."
                                maxlength="500"
                            >
                            <button class="ai-widget-send" id="ai-widget-send">
                                ➤
                            </button>
                        </div>
                    </div>
                </div>
            `;
            
            document.body.appendChild(container);
            
            // Store references
            this.toggleButton = document.getElementById('ai-widget-toggle');
            this.chatContainer = document.getElementById('ai-widget-chat');
            this.closeButton = document.getElementById('ai-widget-close');
            this.messagesContainer = document.getElementById('ai-widget-messages');
            this.input = document.getElementById('ai-widget-input');
            this.sendButton = document.getElementById('ai-widget-send');
            this.typingIndicator = document.getElementById('ai-widget-typing');
        }
        
        attachEventListeners() {
            this.toggleButton.addEventListener('click', () => this.toggleChat());
            this.closeButton.addEventListener('click', () => this.closeChat());
            this.sendButton.addEventListener('click', () => this.sendMessage());
            
            this.input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    this.sendMessage();
                }
            });
            
            this.input.addEventListener('input', () => {
                this.sendButton.disabled = !this.input.value.trim();
            });
        }
        
        toggleChat() {
            this.isOpen = !this.isOpen;
            this.chatContainer.style.display = this.isOpen ? 'flex' : 'none';
            
            if (this.isOpen) {
                this.input.focus();
                this.toggleButton.innerHTML = '✕';
            } else {
                this.toggleButton.innerHTML = '💬';
            }
        }
        
        closeChat() {
            this.isOpen = false;
            this.chatContainer.style.display = 'none';
            this.toggleButton.innerHTML = '💬';
        }
        
        async sendMessage() {
            const message = this.input.value.trim();
            if (!message) return;
            
            // Add user message to UI
            this.addMessage('user', message);
            this.input.value = '';
            this.sendButton.disabled = true;
            
            // Show typing indicator
            this.showTyping(true);
            
            try {
                console.log(`${this.apiBaseUrl}/api/chat`);
                const response = await fetch(`${this.apiBaseUrl}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        message: message,
                        sessionId: this.sessionId
                    })
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                
                const data = await response.json();
                
                // Add assistant response to UI
                this.addMessage('assistant', data.response, data.sources);
                
            } catch (error) {
                console.error('Chat error:', error);
                this.addMessage('assistant', "I'm sorry, I'm having trouble connecting right now. Please try again in a moment.");
            }
            
            this.showTyping(false);
        }
        
        addMessage(role, content, sources = []) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `ai-widget-message ${role}`;
            
            let sourcesHtml = '';
            if (sources && sources.length > 0) {
                sourcesHtml = '<div class="ai-widget-sources">Sources:<br>' +
                    sources.map(source => 
                        `<a href="${source.url}" target="_blank" class="ai-widget-source">${source.title}</a>`
                    ).join('') +
                    '</div>';
            }
            
            messageDiv.innerHTML = `
                <div class="ai-widget-message-content">
                    ${content.replace(/\n/g, '<br>')}
                    ${sourcesHtml}
                </div>
            `;
            
            this.messagesContainer.appendChild(messageDiv);
            this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
            
            // Store message
            this.messages.push({ role, content, sources, timestamp: Date.now() });
        }
        
        showTyping(show) {
            this.typingIndicator.style.display = show ? 'block' : 'none';
            if (show) {
                this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
            }
        }
    }
    
    // Initialize widget when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.AIAssistantWidget = new AIAssistantWidget();
        });
    } else {
        window.AIAssistantWidget = new AIAssistantWidget();
    }
})();
