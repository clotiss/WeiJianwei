/**
 * ===========================================================================
 * Agent 对话浮窗组件 — AI 驱动的政策文件智能问答
 * ===========================================================================
 *
 * 功能：
 * - 浮窗式对话界面，从首页悬浮球唤起
 * - 支持多轮对话（session 机制），理解指代词和追问
 * - 显示 AI 思考过程、引用回答、相关文件卡片
 *
 * 使用方式：
 *   <agent-chat show="{{showChat}}" bind:close="onChatClose" />
 */

const api = require('../../utils/api');

Component({
  properties: {
    /** 是否显示浮窗 */
    show: {
      type: Boolean,
      value: false,
      observer(newVal) {
        if (newVal) {
          this._onShow();
        }
      }
    }
  },

  data: {
    messages: [],
    inputValue: '',
    loading: false,
    scrollToView: '',
    sessionId: null,
    _thinkingOpen: {},   // 记录每条消息的思考过程展开状态
  },

  lifetimes: {
    attached() {
      this._startNewSession();
    }
  },

  methods: {
    // =====================================================================
    // 显示/隐藏
    // =====================================================================

    _onShow() {
      // 首次打开显示欢迎语
      if (this.data.messages.length === 0) {
        this.setData({
          messages: [{
            role: 'assistant',
            content: '你好！我是 AI 政策问答助手。用自然语言问我问题即可，比如：\n\n"最近关于传染病防控的文件"\n"基层医疗机构的设置标准"\n"2024年关于中医药的政策"',
            thinking_steps: [],
            documents: [],
          }]
        });
      }
    },

    onClose() {
      this.triggerEvent('close');
    },

    // =====================================================================
    // 输入与发送
    // =====================================================================

    onInput(e) {
      this.setData({ inputValue: e.detail.value });
    },

    onSend() {
      const query = this.data.inputValue.trim();
      if (!query || this.data.loading) return;

      this.setData({ inputValue: '' });

      const messages = [...this.data.messages, { role: 'user', content: query }];
      const thinkingOpen = { ...this.data._thinkingOpen };

      // AI 占位消息
      const aiPlaceholder = {
        role: 'assistant',
        content: '',
        thinking_steps: ['⏳ 正在思考...'],
        documents: [],
        _loading: true,
      };
      const aiIdx = messages.length;
      messages.push(aiPlaceholder);

      this.setData({
        messages,
        loading: true,
        scrollToView: `msg-${aiIdx}`,
      });

      api.agentSearch(query, this.data.sessionId)
        .then(res => {
          const msgs = this.data.messages;
          msgs[aiIdx] = {
            role: 'assistant',
            content: res.answer || '抱歉，未能生成回答。',
            thinking_steps: res.thinking_steps || [],
            documents: res.documents || [],
            _loading: false,
          };
          thinkingOpen[aiIdx] = false;
          this.setData({
            messages: msgs,
            loading: false,
            scrollToView: `msg-${aiIdx}`,
            _thinkingOpen: thinkingOpen,
          });
        })
        .catch(err => {
          console.error('[agent-chat] API error:', err);
          const msgs = this.data.messages;
          msgs[aiIdx] = {
            role: 'assistant',
            content: '抱歉，网络好像不太稳定，请稍后重试。',
            thinking_steps: ['❌ 请求失败'],
            documents: [],
            _loading: false,
          };
          this.setData({ messages: msgs, loading: false });
        });
    },

    // =====================================================================
    // 思考过程折叠
    // =====================================================================

    onToggleThinking(e) {
      const idx = e.currentTarget.dataset.msgIndex;
      const key = `_thinkingOpen.${idx}`;
      const current = this.data._thinkingOpen[idx];
      this.setData({ [key]: !current });
    },

    // =====================================================================
    // 新对话
    // =====================================================================

    onNewChat() {
      if (this.data.loading) return;
      this._startNewSession();
      this.setData({
        messages: [{
          role: 'assistant',
          content: '新对话已开始，请继续提问。',
          thinking_steps: [],
          documents: [],
        }],
        scrollToView: 'msg-0',
        _thinkingOpen: {},
      });
    },

    _startNewSession() {
      this.setData({
        sessionId: `sess_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      });
    },

    // =====================================================================
    // 文件详情跳转
    // =====================================================================

    onDocTap(e) {
      const docId = e.currentTarget.dataset.docId;
      if (docId) {
        wx.navigateTo({ url: `/pages/detail/detail?id=${docId}` });
      }
    },
  }
});
