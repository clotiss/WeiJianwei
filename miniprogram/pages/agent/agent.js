/**
 * ===========================================================================
 * Agent 对话页 — AI 驱动的自然语言政策文件问答
 * ===========================================================================
 *
 * 功能：
 * - 用自然语言提问，AI 返回带引用的回答和相关文件列表
 * - 支持多轮对话（session 机制），能理解指代词和追问
 * - 显示 AI 思考过程（thinking_steps）
 * - 点击文件卡片可跳转详情页
 *
 * 与普通搜索页的区别：
 * - 搜索页：关键词匹配 → 文件列表
 * - 对话页：自然语言 → AI 理解 + 检索 + 评估 → 回答 + 文件
 */

const api = require('../../utils/api');

Page({
  data: {
    /** 消息列表 [{role:'user'|'assistant', content, thinking_steps, documents}] */
    messages: [],

    /** 用户输入框内容 */
    inputValue: '',

    /** 是否正在等待 AI 回复 */
    loading: false,

    /** 滚动到指定消息 ID */
    scrollToView: '',

    /** 当前会话 ID（null 时每次独立，有值时启用多轮记忆） */
    sessionId: null,
  },

  // =========================================================================
  // 生命周期
  // =========================================================================

  onLoad() {
    // 生成会话 ID，启用多轮对话
    this._startNewSession();
    // 显示欢迎语
    this.setData({
      messages: [{
        role: 'assistant',
        content: '你好！我是 AI 政策问答助手。你可以直接用自然语言问我问题，比如：\n\n• "最近关于传染病防控的文件有哪些？"\n• "基层医疗机构的设置标准是什么？"\n• "2024年关于中医药的文件"',
        thinking_steps: [],
        documents: [],
      }]
    });
  },

  // =========================================================================
  // 用户输入处理
  // =========================================================================

  /** 输入框内容变化 */
  onInput(e) {
    this.setData({ inputValue: e.detail.value });
  },

  /** 点击发送按钮 */
  onSend() {
    const query = this.data.inputValue.trim();
    if (!query || this.data.loading) return;

    // 清空输入框
    this.setData({ inputValue: '' });

    // 添加用户消息到列表
    const userMsg = { role: 'user', content: query };
    const messages = [...this.data.messages, userMsg];
    this.setData({
      messages,
      loading: true,
      scrollToView: `msg-${messages.length - 1}`,
    });

    // 添加 AI 占位消息（显示加载中）
    const aiPlaceholder = {
      role: 'assistant',
      content: '',
      thinking_steps: ['⏳ 正在思考...'],
      documents: [],
      _loading: true,
    };
    this.setData({
      messages: [...this.data.messages, aiPlaceholder],
      scrollToView: `msg-${this.data.messages.length - 1}`,
    });

    // 调用 Agent API
    api.agentSearch(query, this.data.sessionId)
      .then(res => {
        this._onAgentResponse(res);
      })
      .catch(err => {
        this._onAgentError(err);
      });
  },

  /** Agent API 返回成功 */
  _onAgentResponse(res) {
    const messages = [...this.data.messages];
    // 替换最后一个占位消息
    const lastIdx = messages.length - 1;
    messages[lastIdx] = {
      role: 'assistant',
      content: res.answer || '抱歉，未能生成回答。',
      thinking_steps: res.thinking_steps || [],
      documents: res.documents || [],
      _loading: false,
    };

    this.setData({
      messages,
      loading: false,
      scrollToView: `msg-${lastIdx}`,
    });
  },

  /** Agent API 返回失败 */
  _onAgentError(err) {
    console.error('[agent] API error:', err);
    const messages = [...this.data.messages];
    const lastIdx = messages.length - 1;
    messages[lastIdx] = {
      role: 'assistant',
      content: '抱歉，网络好像不太稳定，请稍后重试。',
      thinking_steps: ['❌ 请求失败'],
      documents: [],
      _loading: false,
    };

    this.setData({
      messages,
      loading: false,
      scrollToView: `msg-${lastIdx}`,
    });
  },

  // =========================================================================
  // 会话管理
  // =========================================================================

  /** 开始新对话 */
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
    });
  },

  /** 生成新的会话 ID */
  _startNewSession() {
    this.setData({
      sessionId: `sess_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    });
  },

  // =========================================================================
  // 导航
  // =========================================================================

  /** 点击文件卡片 → 跳转详情页 */
  onDocTap(e) {
    const docId = e.currentTarget.dataset.docId;
    if (docId) {
      wx.navigateTo({ url: `/pages/detail/detail?id=${docId}` });
    }
  },

  /** 切换思考步骤的展开/折叠 */
  onToggleThinking(e) {
    const idx = e.currentTarget.dataset.msgIndex;
    const key = `messages[${idx}]._thinkingOpen`;
    const current = this.data.messages[idx]._thinkingOpen;
    this.setData({ [key]: !current });
  },
});
