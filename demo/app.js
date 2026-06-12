const state = {
  token: localStorage.getItem("conduitToken") || "",
  user: JSON.parse(localStorage.getItem("conduitUser") || "null"),
  authMode: "login",
  articles: [],
  selectedArticle: null,
  recommendations: [],
  recommendationPool: [],
  recommendationRotation: 0,
  articlePage: { limit: 12, offset: 0 },
  comments: [],
  commentPage: { page: 0, pageSize: 6 },
  notifications: [],
  notificationFilter: "article",
  notificationReadFilter: "all",
  favoriteArticles: [],
  articleLibrarySources: [],
  userContent: { overview: null, articles: [], comments: [] },
  userContentTab: "articles",
  userContentFilters: {
    articles: { q: "", status: "all", page: 0, pageSize: 5, total: 0 },
    comments: { q: "", status: "all", page: 0, pageSize: 6, total: 0 },
  },
  editingContent: null,
  drafts: JSON.parse(localStorage.getItem("conduitDrafts") || "[]"),
  polishResult: null,
};

const $ = (id) => document.getElementById(id);
const API_BASE =
  window.API_BASE ||
  localStorage.getItem("conduitApiBase") ||
  `${window.location.protocol === "file:" ? "http:" : window.location.protocol}//${
    window.location.hostname || "127.0.0.1"
  }:8010/api`;
const REQUEST_TIMEOUT_MS = 12000;
const ANALYSIS_TIMEOUT_MS = 30000;
const POLISH_TIMEOUT_MS = 60000;
const ANALYSIS_EMPTY_TEXT = "点击“分析草稿”查看摘要、标签、质量评分和修改建议。";
const POLISH_EMPTY_TEXT =
  "点击“润色正文”，AI 将对正文进行 Critique → Revise → Verify 三阶段润色并生成逐句对比。";
const REVISION_TIMEOUT_MS = 60000;
const QA_TIMEOUT_MS = 60000;

const titles = {
  feedView: ["内容浏览", "今日文章"],
  editorView: ["草稿工作台", "写作台"],
  readerView: ["长文阅读", "沉浸阅读"],
  profileView: ["消息与资料", "账号与通知"],
};

const coverImages = [
  "https://images.unsplash.com/photo-1455390582262-044cdead277a?auto=format&fit=crop&w=900&q=80",
  "https://images.unsplash.com/photo-1499750310107-5fef28a66643?auto=format&fit=crop&w=900&q=80",
  "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=900&q=80",
  "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=900&q=80",
  "https://images.unsplash.com/photo-1519389950473-47ba0277781c?auto=format&fit=crop&w=900&q=80",
  "https://images.unsplash.com/photo-1483058712412-4245e9b90334?auto=format&fit=crop&w=900&q=80",
];

function apiBase() {
  return API_BASE;
}

function headers() {
  return {
    "Content-Type": "application/json",
    ...(state.token ? { Authorization: `Token ${state.token}` } : {}),
  };
}

function articlePayload() {
  return {
    article: {
      title: $("articleTitle").value.trim(),
      description: $("articleDescription").value.trim(),
      body: $("articleBody").value.trim(),
      tagList: $("articleTags")
        .value.split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
    },
  };
}

async function request(path, options = {}) {
  const controller = new AbortController();
  const timeoutMs = Number(options.timeoutMs || REQUEST_TIMEOUT_MS);
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const timeoutMessage = options.timeoutMessage || "请求超时，请确认后端服务已经启动。";
  const response = await fetch(`${apiBase()}${path}`, {
    ...options,
    signal: controller.signal,
    headers: {
      ...headers(),
      ...(options.headers || {}),
    },
  }).catch((error) => {
    if (error.name === "AbortError") {
      throw new Error(timeoutMessage);
    }
    throw new Error("无法连接后端服务，请确认 FastAPI 正在运行。");
  });
  try {
    const text = await response.text();
    const data = text ? JSON.parse(text) : null;
    if (!response.ok) {
      const error = new Error(formatApiError(data));
      error.payload = data?.errors?.[0] || data?.detail || data;
      throw error;
    }
    return data;
  } finally {
    window.clearTimeout(timeout);
  }
}

function formatApiError(data) {
  const detail = data?.errors?.[0] || data?.detail || data;
  if (!detail) {
    return "请求失败。";
  }
  if (typeof detail === "string") {
    return detail;
  }
  if (detail.message) {
    return detail.message;
  }
  return JSON.stringify(detail, null, 2);
}

async function withBusy(button, task) {
  button.disabled = true;
  try {
    return await task();
  } finally {
    button.disabled = false;
  }
}

function saveDraft(label = "手动保存") {
  const draft = {
    id: Date.now(),
    label,
    savedAt: new Date().toISOString(),
    payload: articlePayload().article,
  };
  state.drafts = [draft, ...state.drafts].slice(0, 8);
  localStorage.setItem("conduitDrafts", JSON.stringify(state.drafts));
  renderDrafts();
}

function clearDrafts(options = {}) {
  state.drafts = [];
  localStorage.removeItem("conduitDrafts");
  renderDrafts();
  if (options.clearEditor) {
    clearEditor();
    resetAnalysis();
  }
}

function clearEditor() {
  $("articleTitle").value = "";
  $("articleDescription").value = "";
  $("articleTags").value = "";
  $("articleBody").value = "";
}

function resetAnalysis() {
  $("analysisResult").className = "analysis-empty";
  $("analysisResult").textContent = ANALYSIS_EMPTY_TEXT;
}

function resetPolish() {
  state.polishResult = null;
  $("polishResult").className = "polish-empty";
  $("polishResult").textContent = POLISH_EMPTY_TEXT;
}

function restoreDraft(id) {
  const draft = state.drafts.find((item) => String(item.id) === String(id));
  if (!draft) {
    return;
  }
  $("articleTitle").value = draft.payload.title || "";
  $("articleDescription").value = draft.payload.description || "";
  $("articleTags").value = (draft.payload.tagList || []).join(",");
  $("articleBody").value = draft.payload.body || "";
  toast("草稿已恢复");
}

function toast(message, type = "info") {
  const box = $("toast");
  box.textContent = message;
  box.className = `toast show ${type === "error" ? "error" : ""}`;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => {
    box.className = "toast";
  }, 3200);
}

function syncModalState() {
  const hasOpenModal = !$("contentEditModal").classList.contains("hidden");
  const hasOpenDrawer = !$("articleLibraryDrawer").classList.contains("hidden");
  document.body.classList.toggle("modal-open", hasOpenModal || hasOpenDrawer);
}

function openArticleLibraryDrawer() {
  $("articleLibraryDrawer").classList.remove("hidden");
  syncModalState();
  $("articleLibraryQuestion").focus();
}

function closeArticleLibraryDrawer() {
  $("articleLibraryDrawer").classList.add("hidden");
  syncModalState();
}

function setToken(token, user = state.user) {
  state.token = token || "";
  state.user = user;
  localStorage.setItem("conduitToken", state.token);
  if (user) {
    localStorage.setItem("conduitUser", JSON.stringify(user));
  } else {
    localStorage.removeItem("conduitUser");
  }
  renderAccount();
}

function renderAccount() {
  const name = state.user?.username || "未登录";
  $("accountName").textContent = name;
  $("profileName").textContent = name;
  $("profileEmail").textContent = state.user?.email || "登录后显示邮箱。";
  $("avatar").textContent = name === "未登录" ? "?" : name.slice(0, 1).toUpperCase();
  $("logoutBtn").classList.toggle("hidden", !state.token);
  $("authView").classList.toggle("active", !state.token);
  document.body.classList.toggle("is-authenticated", Boolean(state.token));
}

function switchView(viewId) {
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view.id === viewId);
  });
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === viewId);
  });
  const [eyebrow, title] = titles[viewId];
  $("eyebrow").textContent = eyebrow;
  $("viewTitle").textContent = title;
  if (viewId === "profileView" && state.token) {
    $("userContentStatus").value = userContentFilterState().status;
    $("userContentQuery").value = userContentFilterState().q;
    loadNotifications().catch((error) => toast(error.message, "error"));
    loadUserContent().catch((error) => toast(error.message, "error"));
    loadFavoriteArticles().catch((error) => toast(error.message, "error"));
  }
}

function setAuthMode(mode) {
  state.authMode = mode;
  document.querySelectorAll("[data-auth-mode]").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.authMode === mode);
  });
  $("usernameField").classList.toggle("hidden", mode !== "register");
  $("authSubmitBtn").textContent = mode === "register" ? "注册" : "登录";
  $("authHint").textContent =
    mode === "register" ? "已有账号时切换到登录。" : "没有账号时切换到注册。";
}

function renderArticles(data) {
  state.articles = (data?.articles || [])
    .map(normalizeArticleResult)
    .filter((article) => article?.slug);
  $("articleCount").textContent = String(state.articles.length);
  if (!state.articles.length) {
    $("articleGrid").innerHTML = `
      <div class="article-card empty-card">
        <div class="article-content">
          <p class="eyebrow">Empty</p>
          <h3>还没有文章</h3>
          <p>去写作页发布第一篇文章，或换一个关键词重新搜索。</p>
        </div>
      </div>
    `;
    renderArticlePager();
    return;
  }
  $("articleGrid").innerHTML = state.articles
    .map((article) => {
      const tags = article.tagList || [];
      const category = tags[0] || "journal";
      return `
        <article class="article-card" data-slug="${escapeHtml(article.slug)}">
          <div class="article-cover">
            <img alt="" src="${coverForArticle(article)}" loading="lazy" />
          </div>
          <div class="article-content">
            <div class="meta">
              <span>${escapeHtml(category)}</span>
              <span>${formatDate(article.createdAt)}</span>
              <span>${readingTime(article.body)} min read</span>
            </div>
            <h3>${escapeHtml(article.title)}</h3>
            <p>${escapeHtml(article.description || excerpt(article.body, 120))}</p>
            ${
              $("filterQuery").value.trim()
                ? `<p class="muted">命中原因：${escapeHtml(searchExplanation(article, $("filterQuery").value.trim()))}</p>`
                : ""
            }
            <div class="tags">
              ${tags
                .slice(0, 4)
                .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
                .join("")}
            </div>
            <div class="meta">
              <span>By ${escapeHtml(article.author?.username || "unknown")}</span>
              <span>${article.favoritesCount || 0} favorites</span>
            </div>
            <div class="actions">
              <button
                class="ghost ${article.favorited ? "active-favorite" : ""}"
                data-toggle-favorite="${escapeHtml(article.slug)}"
                type="button"
              >${article.favorited ? "已收藏" : "收藏文章"}</button>
            </div>
          </div>
        </article>
      `;
    })
    .join("");
  renderArticlePager();
}

function renderArticle(article) {
  state.selectedArticle = article;
  state.recommendations = [];
  state.recommendationPool = [];
  state.recommendationRotation = 0;
  state.commentPage.page = 0;
  const contentStatus = article.contentStatus || "visible";
  const tags = (article.tagList || [])
    .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
    .join("");
  $("readerArticle").className = "reader-article";
  $("readerArticle").innerHTML = `
    <div class="reader-hero">
      <div class="reader-cover">
        <img alt="" src="${coverForArticle(article)}" />
      </div>
    </div>
    <div class="reader-main">
      <div class="meta">
        <span>${escapeHtml(article.author?.username || "unknown")}</span>
        <span>${formatDate(article.createdAt)}</span>
        <span>${readingTime(article.body)} min read</span>
        <span>${article.favoritesCount || 0} favorites</span>
        ${
          contentStatus !== "visible"
            ? `<span>${contentStatus === "pending" ? "待审核" : "不显示"}</span>`
            : ""
        }
      </div>
      <h2>${escapeHtml(article.title)}</h2>
      <p class="lead">${escapeHtml(article.description)}</p>
      <div class="tags">${tags}</div>
      <div class="actions">
        <button
          class="ghost ${article.favorited ? "active-favorite" : ""}"
          data-toggle-favorite="${escapeHtml(article.slug)}"
          type="button"
        >${article.favorited ? "已收藏" : "收藏文章"}</button>
        <button class="ghost" data-report-article="${escapeHtml(article.slug)}" type="button">举报文章</button>
      </div>
      <div class="body">${escapeHtml(article.body)}</div>
    </div>
  `;
  if (contentStatus === "visible") {
    loadComments(article.slug).catch((error) => toast(error.message, "error"));
    renderRecommendations({ articles: [] });
    loadRecommendations(article.slug, { auto: true }).catch((error) =>
      toast(error.message, "error"),
    );
  } else {
    renderComments({ comments: [] });
    $("recommendationsList").innerHTML = `<div class="comment"><p class="muted">内容通过审核后可加载相关推荐。</p></div>`;
  }
  $("moderationResult").className = "moderation-empty";
  $("moderationResult").textContent = "评论将在发表前自动审核。";
}

function renderComments(data) {
  state.comments = data?.comments || [];
  renderCommentPage();
}

function renderCommentPage() {
  const comments = state.comments;
  if (!comments.length) {
    $("commentsList").innerHTML = `<div class="comment"><p class="muted">暂无评论。</p></div>`;
    renderCommentsPager();
    return;
  }
  const start = state.commentPage.page * state.commentPage.pageSize;
  const visibleComments = comments.slice(start, start + state.commentPage.pageSize);
  $("commentsList").innerHTML = visibleComments
    .map(
      (comment) => `
        <div class="comment">
          <p>${escapeHtml(comment.body)}</p>
          <div class="meta">
            <span>${escapeHtml(comment.author?.username || "")}</span>
            <span>#${comment.id}</span>
            <span>${Number(comment.likesCount || 0)} 赞</span>
          </div>
          <div class="actions">
            <button
              class="ghost ${comment.liked ? "active-favorite" : ""}"
              data-toggle-comment-like="${comment.id}"
              type="button"
            >${comment.liked ? "已点赞" : "点赞"}</button>
            <button class="ghost" data-report-comment="${comment.id}" type="button">举报</button>
          </div>
        </div>
      `,
    )
    .join("");
  renderCommentsPager();
}

function renderAnalysis(data) {
  const analysis = data.analysis;
  $("analysisResult").className = "analysis-box";
  $("analysisResult").innerHTML = `
    <div class="score">${analysis.contentScore}</div>
    <div>
      <p class="eyebrow">Summary</p>
      <p>${escapeHtml(analysis.summary)}</p>
    </div>
    <div>
      <p class="eyebrow">Tags</p>
      <div class="tags">
        ${(analysis.recommendedTagList || [])
          .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
          .join("")}
      </div>
    </div>
    <div class="analysis-suggestions">
      <p class="eyebrow">Suggestions</p>
      <ul class="suggestion-list">${(analysis.suggestions || [])
        .map(
          (item) => `
            <li>
              <span>${escapeHtml(item)}</span>
              <button
                class="ghost inline-suggestion-action"
                data-revise-suggestion="${escapeHtml(item)}"
                type="button"
              >针对改写</button>
            </li>
          `,
        )
        .join("")}</ul>
    </div>
    <p class="muted">Model: ${escapeHtml(analysis.model || "unknown")}</p>
  `;
}

function renderAnalysisLoading() {
  $("analysisResult").className = "analysis-empty loading-state";
  $("analysisResult").innerHTML = `
    <div class="loading-copy">
      <strong>正在分析草稿...</strong>
      <p>AI 正在生成摘要、标签和修改建议。</p>
    </div>
  `;
}

function renderAnalysisError(message) {
  $("analysisResult").className = "analysis-empty";
  $("analysisResult").innerHTML = `
    <div class="loading-copy">
      <strong>分析未完成</strong>
      <p>${escapeHtml(message || "请稍后重试。")}</p>
    </div>
  `;
}

function renderPolish(data) {
  const result = data.result;
  state.polishResult = result.polished;
  const scorePercent = (Number(result.improvementScore || 0) * 100).toFixed(0);
  $("polishResult").className = "polish-box";
  $("polishResult").innerHTML = `
    <div class="polish-head">
      <div class="score">${scorePercent}</div>
      <div>
        <p class="eyebrow">Polish Score</p>
        <p class="muted">${result.iterations} 轮润色 · ${escapeHtml(result.model || "unknown")}</p>
      </div>
    </div>
    <div class="polish-comparison">
      <section class="comparison-pane">
        <p class="eyebrow">原文</p>
        <div class="comparison-body">${escapeHtml(result.original || "")}</div>
      </section>
      <section class="comparison-pane polished-pane">
        <p class="eyebrow">润色后</p>
        <div class="comparison-body">${escapeHtml(result.polished || "")}</div>
      </section>
    </div>
    <div>
      <p class="eyebrow">整体评估</p>
      <p>${escapeHtml(result.critique || "")}</p>
    </div>
    <div>
      <p class="eyebrow">改动摘要</p>
      <ul>${(result.changesSummary || [])
        .map((item) => `<li>${escapeHtml(item)}</li>`)
        .join("")}</ul>
    </div>
    <div>
      <p class="eyebrow">逐句对比</p>
      <div class="diff-view">${(result.diff || [])
        .map(
          (entry) =>
            `<span class="diff-sentence ${escapeHtml(entry.op)}">${escapeHtml(entry.text)}</span>`,
        )
        .join(" ")}</div>
    </div>
    <div class="actions">
      <button id="applyPolishBtn" type="button">一键替换正文</button>
    </div>
  `;
}

function renderSuggestionRevision(data) {
  const result = data.result;
  state.polishResult = result.revised;
  const confidencePercent = (Number(result.confidence || 0) * 100).toFixed(0);
  $("polishResult").className = "polish-box";
  $("polishResult").innerHTML = `
    <div class="polish-head">
      <div class="score">${confidencePercent}</div>
      <div>
        <p class="eyebrow">Suggestion Revision</p>
        <p class="muted">第 ${Number(result.changedParagraphIndex || 0) + 1} 段 · ${escapeHtml(
          result.model || "unknown",
        )}</p>
      </div>
    </div>
    <div class="revision-source">
      <p class="eyebrow">选中的建议</p>
      <p>${escapeHtml(result.suggestion || "")}</p>
    </div>
    <div class="polish-comparison">
      <section class="comparison-pane">
        <p class="eyebrow">原文</p>
        <div class="comparison-body">${escapeHtml(result.original || "")}</div>
      </section>
      <section class="comparison-pane polished-pane">
        <p class="eyebrow">改写后</p>
        <div class="comparison-body">${escapeHtml(result.revised || "")}</div>
      </section>
    </div>
    <div>
      <p class="eyebrow">改写理由</p>
      <p>${escapeHtml(result.rationale || "")}</p>
    </div>
    <div>
      <p class="eyebrow">改动摘要</p>
      <ul>${(result.changesSummary || [])
        .map((item) => `<li>${escapeHtml(item)}</li>`)
        .join("")}</ul>
    </div>
    <div>
      <p class="eyebrow">逐句对比</p>
      <div class="diff-view">${(result.diff || [])
        .map(
          (entry) =>
            `<span class="diff-sentence ${escapeHtml(entry.op)}">${escapeHtml(entry.text)}</span>`,
        )
        .join(" ")}</div>
    </div>
    <div class="actions">
      <button id="applyPolishBtn" type="button">一键替换正文</button>
    </div>
  `;
}

function renderPolishLoading(instruction) {
  $("polishResult").className = "polish-empty loading-state";
  $("polishResult").innerHTML = `
    <div class="loading-copy">
      <strong>正在润色正文...</strong>
      <p>AI 正在执行 Critique → Revise → Verify 流程。</p>
      <p class="muted">当前指令：${escapeHtml(instruction)}</p>
    </div>
  `;
}

function renderSuggestionRevisionLoading(suggestion) {
  $("polishResult").className = "polish-empty loading-state";
  $("polishResult").innerHTML = `
    <div class="loading-copy">
      <strong>正在根据建议改写...</strong>
      <p>AI 正在定位相关段落，并尽量保留无关内容不变。</p>
      <p class="muted">选中的建议：${escapeHtml(suggestion)}</p>
    </div>
  `;
}

function renderPolishError(message) {
  $("polishResult").className = "polish-empty";
  $("polishResult").innerHTML = `
    <div class="loading-copy">
      <strong>润色未完成</strong>
      <p>${escapeHtml(message || "请稍后重试。")}</p>
    </div>
  `;
}

function renderArticleLibraryAnswer(data) {
  const result = data.result;
  state.articleLibrarySources = result.sources || [];
  const citations = new Set(result.citations || []);
  $("articleLibraryAnswer").className = "qa-box";
  $("articleLibraryAnswer").innerHTML = `
    <div class="qa-answer">
      <p class="eyebrow">Answer</p>
      <p>${escapeHtml(result.answer || "")}</p>
      <p class="muted">Model: ${escapeHtml(result.model || "unknown")}</p>
    </div>
    <div>
      <p class="eyebrow">来源文章</p>
      <div class="qa-source-list">
        ${state.articleLibrarySources
          .map((source, index) => {
            const article = normalizeArticleResult(source.article);
            const cited = citations.has(article.slug);
            return `
              <button class="qa-source" data-qa-source-index="${index}" type="button">
                <strong>${escapeHtml(article.title)}</strong>
                <span class="muted">${escapeHtml(source.reason || "与问题语义相关")}</span>
                <span class="meta">
                  <span>${cited ? "已引用" : "相关来源"}</span>
                  <span>${Math.round(Number(source.similarityScore || 0) * 100)}% match</span>
                </span>
              </button>
            `;
          })
          .join("")}
      </div>
    </div>
    ${
      (result.suggestedQueries || []).length
        ? `<div>
            <p class="eyebrow">可以继续问</p>
            <div class="tags">
              ${result.suggestedQueries
                .map(
                  (item) =>
                    `<button class="ghost qa-followup" data-qa-followup="${escapeHtml(
                      item,
                    )}" type="button">${escapeHtml(item)}</button>`,
                )
                .join("")}
            </div>
          </div>`
        : ""
    }
  `;
}

function renderArticleLibraryLoading(question) {
  $("articleLibraryAnswer").className = "qa-empty loading-state";
  $("articleLibraryAnswer").innerHTML = `
    <div class="loading-copy">
      <strong>正在检索文章库...</strong>
      <p>AI 会先找相关文章，再基于来源生成回答。</p>
      <p class="muted">问题：${escapeHtml(question)}</p>
    </div>
  `;
}

function renderArticleLibraryError(message) {
  state.articleLibrarySources = [];
  $("articleLibraryAnswer").className = "qa-empty";
  $("articleLibraryAnswer").innerHTML = `
    <div class="loading-copy">
      <strong>文章库助手暂不可用</strong>
      <p>${escapeHtml(message || "请稍后重试。")}</p>
    </div>
  `;
}

function renderModeration(data) {
  const moderation = data.moderation || data;
  const blocked = !moderation.allowed;
  $("moderationResult").className = "moderation-box";
  $("moderationResult").innerHTML = `
    <span class="moderation-status ${blocked ? "blocked" : ""}">
      ${blocked ? "需拦截" : "可发布"}
    </span>
    <div>
      <p class="eyebrow">${escapeHtml(moderation.category)} / ${escapeHtml(moderation.severity)}</p>
      <p>${escapeHtml(moderation.reason)}</p>
    </div>
    ${
      moderation.suggestedRevision
        ? `<div><p class="eyebrow">Revision</p><p>${escapeHtml(
            moderation.suggestedRevision,
          )}</p></div>`
        : ""
    }
    <p class="muted">Confidence ${(Number(moderation.confidence || 0) * 100).toFixed(
      0,
    )}% · ${escapeHtml(moderation.model || "unknown")}</p>
  `;
}

function renderArticleRejection(errorPayload) {
  const analysis = errorPayload?.analysis;
  if (!analysis) {
    return;
  }
  $("analysisResult").className = "analysis-box";
  $("analysisResult").innerHTML = `
    <div class="score">${analysis.contentScore}</div>
    <div>
      <p class="eyebrow">Review Blocked</p>
      <p>${escapeHtml(errorPayload.message || "文章发布前审核未通过。")}</p>
    </div>
    <div>
      <p class="eyebrow">Risk Labels</p>
      <div class="tags">
        ${
          (analysis.riskLabels || [])
            .map((label) => `<span class="tag danger">${escapeHtml(label)}</span>`)
            .join("") || `<span class="tag danger">low-score</span>`
        }
      </div>
    </div>
    <div>
      <p class="eyebrow">Suggestions</p>
      <ul>${(analysis.suggestions || [])
        .map((item) => `<li>${escapeHtml(item)}</li>`)
        .join("")}</ul>
    </div>
    <p class="muted">Model: ${escapeHtml(analysis.model || "unknown")}</p>
  `;
}

function renderRecommendations(data) {
  const incoming = data?.articles || [];
  if (incoming.length) {
    state.recommendationPool = dedupeRecommendations([
      ...state.recommendationPool,
      ...incoming,
    ]);
  }
  state.recommendations = state.recommendationPool.slice(0, 5);
  if (!state.recommendations.length) {
    $("recommendationsList").innerHTML = `<div class="comment"><p class="muted">暂无相关推荐。</p></div>`;
    return;
  }
  $("recommendationsList").innerHTML = state.recommendations
    .map((item, index) => renderRecommendationItem(item, index))
    .join("");
}

function renderRecommendationItem(item, index) {
  const article = item.article;
  const score = Number(item.similarityScore || 0);
  return `
    <article class="recommendation-item" data-index="${index}">
      <div class="similarity">${score ? `${(score * 100).toFixed(0)}% match` : "内容相关"}</div>
      <h3>${escapeHtml(article.title)}</h3>
      <p>${escapeHtml(article.description)}</p>
      <p class="muted">${escapeHtml(item.reason || "与当前文章内容相近")}</p>
      <div class="meta">
        <span>${readingTime(article.body)} min read</span>
        <span>${formatDate(article.createdAt)}</span>
      </div>
    </article>
  `;
}

function rotateRecommendations() {
  if (!state.recommendationPool.length) {
    renderRecommendations({ articles: [] });
    return;
  }
  state.recommendationRotation =
    (state.recommendationRotation + 5) % state.recommendationPool.length;
  const rotated = [
    ...state.recommendationPool.slice(state.recommendationRotation),
    ...state.recommendationPool.slice(0, state.recommendationRotation),
  ];
  state.recommendations = rotated.slice(0, 5);
  $("recommendationsList").innerHTML = state.recommendations
    .map((item, index) => renderRecommendationItem(item, index))
    .join("");
}

function dedupeRecommendations(items) {
  const seen = new Set();
  return items.filter((item) => {
    const slug = item?.article?.slug;
    if (!slug || seen.has(slug)) {
      return false;
    }
    seen.add(slug);
    return true;
  });
}

function renderArticlePager() {
  const hasPrev = state.articlePage.offset > 0;
  const hasNext = state.articles.length === state.articlePage.limit;
  const page = Math.floor(state.articlePage.offset / state.articlePage.limit) + 1;
  $("articlePager").innerHTML = `
    <button class="ghost" data-article-page="prev" type="button" ${
      hasPrev ? "" : "disabled"
    }>上一页</button>
    <span>第 ${page} 页</span>
    <button class="ghost" data-article-page="next" type="button" ${
      hasNext ? "" : "disabled"
    }>下一页</button>
  `;
}

function renderCommentsPager() {
  const totalPages = Math.max(
    1,
    Math.ceil(state.comments.length / state.commentPage.pageSize),
  );
  const page = Math.min(state.commentPage.page, totalPages - 1);
  state.commentPage.page = page;
  $("commentsPager").innerHTML = `
    <button class="ghost" data-comment-page="prev" type="button" ${
      page > 0 ? "" : "disabled"
    }>上一页</button>
    <span>${state.comments.length} 条评论 · 第 ${page + 1}/${totalPages} 页</span>
    <button class="ghost" data-comment-page="next" type="button" ${
      page < totalPages - 1 ? "" : "disabled"
    }>下一页</button>
  `;
}

function renderDrafts() {
  const target = $("draftVersions");
  if (!target) {
    return;
  }
  if (!state.drafts.length) {
    target.innerHTML = `<div class="comment"><p class="muted">暂无草稿版本。</p></div>`;
    return;
  }
  target.innerHTML = state.drafts
    .map(
      (draft) => `
        <button class="draft-item" data-draft-id="${draft.id}" type="button">
          <strong>${escapeHtml(draft.payload.title || "未命名草稿")}</strong>
          <span>${escapeHtml(draft.label)} · ${formatDate(draft.savedAt)}</span>
        </button>
      `,
    )
    .join("");
}

function renderNotifications(data) {
  state.notifications = data?.notifications || [];
  syncNotificationFilters();
  const notifications = state.notifications.filter((item) =>
    notificationMatchesFilter(item, state.notificationFilter, state.notificationReadFilter),
  );
  if (!notifications.length) {
    $("notificationsList").innerHTML = `<div class="comment"><p class="muted">暂无通知。</p></div>`;
    return;
  }
  $("notificationsList").innerHTML = notifications
    .map(
      (item) => `
        <article class="admin-row ${item.isRead ? "" : "unread"}" data-id="${item.id}">
          <div>
            <h3>${escapeHtml(item.title)}</h3>
            <p>${escapeHtml(item.body)}</p>
            <div class="meta">
              <span>${escapeHtml(item.notificationType)}</span>
              <span>${escapeHtml(item.articleTitle || item.articleSlug || item.contentType)}</span>
              <span>${formatDate(item.createdAt)}</span>
              <span>${item.isRead ? "已读" : "未读"}</span>
            </div>
          </div>
          ${
            item.isRead
              ? ""
              : `<button class="ghost" data-read-notification="${item.id}" type="button">已读</button>`
          }
        </article>
      `,
    )
    .join("");
}

function renderFavoriteArticles(data) {
  state.favoriteArticles = (data?.articles || []).map(normalizeArticleResult);
  if (!state.favoriteArticles.length) {
    $("favoriteArticlesList").innerHTML = `<div class="comment"><p class="muted">还没有收藏文章。</p></div>`;
    return;
  }
  $("favoriteArticlesList").innerHTML = state.favoriteArticles
    .map(
      (article) => `
        <article class="admin-row clickable-row" data-favorite-slug="${escapeHtml(article.slug)}">
          <div>
            <h3>${escapeHtml(article.title)}</h3>
            <p>${escapeHtml(article.description || excerpt(article.body, 100))}</p>
            <div class="meta">
              <span>${escapeHtml(article.author?.username || "unknown")}</span>
              <span>${article.favoritesCount || 0} favorites</span>
              <span>${formatDate(article.createdAt)}</span>
            </div>
          </div>
          <div class="actions">
            <button
              class="ghost active-favorite"
              data-toggle-favorite="${escapeHtml(article.slug)}"
              type="button"
            >已收藏</button>
          </div>
        </article>
      `,
    )
    .join("");
}

function renderUserContent(data = state.userContent) {
  state.userContent = {
    overview: data?.overview || null,
    articles: data?.articles || [],
    comments: data?.comments || [],
  };
  if (data?.contentType === "articles") {
    state.userContentFilters.articles.total = Number(data?.articlesCount || 0);
  }
  if (data?.contentType === "comments") {
    state.userContentFilters.comments.total = Number(data?.commentsCount || 0);
  }
  renderUserContentOverview(state.userContent.overview);
  syncUserContentTabs();
  const items =
    state.userContentTab === "articles" ? state.userContent.articles : state.userContent.comments;
  if (!items.length) {
    $("userContentList").innerHTML = `<div class="comment"><p class="muted">暂无内容。</p></div>`;
    renderUserContentPager();
    return;
  }
  $("userContentList").innerHTML = items
    .map((item) =>
      state.userContentTab === "articles"
        ? renderUserArticleItem(item)
        : renderUserCommentItem(item),
    )
    .join("");
  renderUserContentPager();
}

function renderUserContentOverview(overview) {
  if (!overview) {
    $("userContentOverview").innerHTML = "";
    return;
  }
  $("userContentOverview").innerHTML = [
    statCardLite("待审核文章", overview.pendingArticles),
    statCardLite("隐藏文章", overview.hiddenArticles),
    statCardLite("待审核评论", overview.pendingComments),
    statCardLite("隐藏评论", overview.hiddenComments),
  ].join("");
}

function statCardLite(label, value) {
  return `
    <div class="stat-card">
      <span>${escapeHtml(label)}</span>
      <strong>${Number(value || 0)}</strong>
    </div>
  `;
}

function renderUserArticleItem(item) {
  return `
    <article class="admin-row" data-user-content-type="article" data-user-content-id="${escapeHtml(item.slug)}">
      <div>
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.description || excerpt(item.body, 120))}</p>
        <div class="meta">
          <span class="status-pill ${escapeHtml(item.contentStatus || "visible")}">${escapeHtml(contentStatusLabel(item.contentStatus || "visible"))}</span>
          <span>${escapeHtml(reviewStatusLabel(item.latestReviewStatus || "approved"))}</span>
          <span>${escapeHtml(actionLabel(item.latestAction || "manual_status_update"))}</span>
          <span>${formatDate(item.updatedAt)}</span>
        </div>
        ${
          item.latestReviewNote
            ? `<p class="row-note">最近备注：${escapeHtml(item.latestReviewNote)}</p>`
            : ""
        }
      </div>
      <div class="actions">
        <button class="ghost" data-edit-user-article="${escapeHtml(item.slug)}" type="button">编辑</button>
        ${
          item.contentStatus !== "visible"
            ? `<button data-resubmit-article="${escapeHtml(item.slug)}" type="button">重新提交</button>`
            : ""
        }
      </div>
    </article>
  `;
}

function renderUserCommentItem(item) {
  return `
    <article class="admin-row" data-user-content-type="comment" data-user-content-id="${item.id}">
      <div>
        <h3>${escapeHtml(item.articleTitle || item.articleSlug || `评论 #${item.id}`)}</h3>
        <p>${escapeHtml(item.body)}</p>
        <div class="meta">
          <span class="status-pill ${escapeHtml(item.contentStatus || "visible")}">${escapeHtml(contentStatusLabel(item.contentStatus || "visible"))}</span>
          <span>${escapeHtml(reviewStatusLabel(item.latestReviewStatus || "approved"))}</span>
          <span>${escapeHtml(actionLabel(item.latestAction || "manual_status_update"))}</span>
          <span>${formatDate(item.updatedAt)}</span>
        </div>
        ${
          item.latestReviewNote
            ? `<p class="row-note">最近备注：${escapeHtml(item.latestReviewNote)}</p>`
            : ""
        }
      </div>
      <div class="actions">
        <button class="ghost" data-edit-user-comment="${item.id}" type="button">编辑</button>
        ${
          item.contentStatus !== "visible"
            ? `<button data-resubmit-comment="${item.id}" type="button">重新提交</button>`
            : ""
        }
      </div>
    </article>
  `;
}

function syncUserContentTabs() {
  document.querySelectorAll("[data-user-content-tab]").forEach((item) => {
    const active = item.dataset.userContentTab === state.userContentTab;
    item.classList.toggle("active", active);
    item.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function notificationMatchesFilter(item, filter, readFilter) {
  return (
    notificationCategory(item) === filter &&
    notificationReadStateMatches(item, readFilter)
  );
}

function notificationReadStateMatches(item, filter) {
  if (filter === "unread") {
    return !item.isRead;
  }
  if (filter === "read") {
    return item.isRead;
  }
  return true;
}

function notificationCategory(item) {
  const type = item.notificationType || "";
  const contentType = item.contentType || "";
  if (type.startsWith("report_") || type.includes("report")) {
    return "report";
  }
  if (contentType === "comment" || type.startsWith("comment_") || type.includes("comment")) {
    return "comment";
  }
  return "article";
}

function setNotificationFilter(filter, options = {}) {
  state.notificationFilter = filter || "article";
  syncNotificationFilters();
  if (options.render !== false) {
    renderNotifications({ notifications: state.notifications });
  }
}

function setNotificationReadFilter(filter, options = {}) {
  state.notificationReadFilter = filter || "all";
  syncNotificationFilters();
  if (options.render !== false) {
    renderNotifications({ notifications: state.notifications });
  }
}

function setUserContentTab(tab) {
  state.userContentTab = tab || "articles";
  state.userContentFilters[state.userContentTab].page = 0;
  loadUserContent().catch((error) => toast(error.message, "error"));
}

function userContentFilterState() {
  return state.userContentFilters[state.userContentTab];
}

function renderUserContentPager() {
  const filters = userContentFilterState();
  const totalPages = Math.max(1, Math.ceil(Number(filters.total || 0) / filters.pageSize));
  $("userContentList").insertAdjacentHTML(
    "beforeend",
    `
      <div class="pager inline-pager">
        <button class="ghost" data-user-content-page="prev" type="button" ${
          filters.page > 0 ? "" : "disabled"
        }>上一页</button>
        <span>第 ${filters.page + 1}/${Math.max(1, totalPages)} 页</span>
        <button class="ghost" data-user-content-page="next" type="button" ${
          filters.page < Math.max(1, totalPages) - 1 ? "" : "disabled"
        }>下一页</button>
      </div>
    `,
  );
}

function contentStatusLabel(status) {
  if (status === "pending") {
    return "待审核";
  }
  if (status === "hidden") {
    return "不显示";
  }
  return "显示中";
}

function reviewStatusLabel(status) {
  if (status === "pending") {
    return "待复核";
  }
  if (status === "rejected") {
    return "未通过";
  }
  if (status === "approved") {
    return "已通过";
  }
  return "已更新";
}

function actionLabel(action) {
  const labels = {
    ai_pending_review: "AI 初筛待人工复核",
    moderation_approve: "管理员审核通过",
    moderation_reject: "管理员审核驳回",
    author_resubmit: "作者重新提交",
    manual_status_update: "状态调整",
    report_ignore: "举报被驳回",
    report_hide: "举报被采纳",
  };
  return labels[action] || "最近有处理记录";
}

function syncNotificationFilters() {
  document.querySelectorAll(".notification-tabs .tab").forEach((item) => {
    item.classList.remove("active");
    item.setAttribute("aria-pressed", "false");
  });
  document.querySelectorAll("[data-notification-filter]").forEach((item) => {
    if (item.dataset.notificationFilter === state.notificationFilter) {
      item.classList.add("active");
      item.setAttribute("aria-pressed", "true");
    }
  });
  document.querySelectorAll(".notification-state-tabs .tab").forEach((item) => {
    item.classList.remove("active");
    item.setAttribute("aria-pressed", "false");
  });
  document.querySelectorAll("[data-notification-read-filter]").forEach((item) => {
    if (item.dataset.notificationReadFilter === state.notificationReadFilter) {
      item.classList.add("active");
      item.setAttribute("aria-pressed", "true");
    }
  });
}

async function loadArticles(options = {}) {
  if (options.reset) {
    state.articlePage.offset = 0;
  }
  const keyword = $("filterQuery").value.trim();
  const params = new URLSearchParams({
    limit: String(state.articlePage.limit),
    offset: String(state.articlePage.offset),
  });
  if (keyword) {
    params.set("q", keyword);
  }
  const path = `/articles?${params.toString()}`;
  const data = await request(path);
  renderArticles(data);
  return data;
}

async function askArticleLibrary(question) {
  const trimmed = question.trim();
  if (!trimmed) {
    throw new Error("问题不能为空。");
  }
  renderArticleLibraryLoading(trimmed);
  const data = await request("/articles/ai/ask", {
    method: "POST",
    body: JSON.stringify({ question: trimmed, limit: 5 }),
    timeoutMs: QA_TIMEOUT_MS,
    timeoutMessage: "文章库问答耗时较长，请确认后端 AI 服务已经启动后重试。",
  });
  renderArticleLibraryAnswer(data);
  return data;
}

async function loadComments(slug = state.selectedArticle?.slug) {
  if (!slug) {
    renderComments({ comments: [] });
    return null;
  }
  const data = await request(`/articles/${encodeURIComponent(slug)}/comments`);
  state.commentPage.page = 0;
  renderComments(data);
  return data;
}

async function loadRecommendations(slug = state.selectedArticle?.slug, options = {}) {
  if (!slug) {
    renderRecommendations({ articles: [] });
    return null;
  }
  if ((state.selectedArticle?.contentStatus || "visible") !== "visible") {
    renderRecommendations({ articles: [] });
    return null;
  }
  if (!options.silent) {
    $("recommendationsList").textContent = "正在计算相关推荐...";
  }
  const data = await request(
    `/articles/${encodeURIComponent(slug)}/recommendations?limit=8`,
  ).catch(() => ({ articles: [] }));
  renderRecommendations(data);
  return data;
}

async function loadNotifications() {
  if (!state.token) {
    renderNotifications({ notifications: [] });
    return null;
  }
  const data = await request("/user/notifications?limit=30");
  renderNotifications(data);
  return data;
}

async function loadFavoriteArticles() {
  if (!state.token || !state.user?.username) {
    renderFavoriteArticles({ articles: [] });
    return null;
  }
  const params = new URLSearchParams({
    favorited: state.user.username,
    limit: "20",
    offset: "0",
  });
  const data = await request(`/articles?${params.toString()}`);
  renderFavoriteArticles(data);
  return data;
}

async function loadUserContent() {
  if (!state.token) {
    renderUserContent({
      overview: null,
      articles: [],
      comments: [],
      contentType: state.userContentTab,
      articlesCount: 0,
      commentsCount: 0,
    });
    return null;
  }
  const filters = userContentFilterState();
  const params = new URLSearchParams({
    type: state.userContentTab,
    status: filters.status,
    limit: String(filters.pageSize),
    offset: String(filters.page * filters.pageSize),
  });
  if (filters.q) {
    params.set("q", filters.q);
  }
  const data = await request(`/user/content?${params.toString()}`);
  renderUserContent(data);
  return data;
}

async function reportArticle(slug) {
  const detail = window.prompt("请输入举报原因", "内容存在风险");
  if (!detail) {
    return null;
  }
  const data = await request(`/articles/${encodeURIComponent(slug)}/report`, {
    method: "POST",
    body: JSON.stringify({
      report: {
        reason: detail.slice(0, 80),
        detail,
      },
    }),
  });
  toast("举报已提交");
  return data;
}

async function reportComment(commentId) {
  if (!state.selectedArticle) {
    throw new Error("请先选择一篇文章。");
  }
  const detail = window.prompt("请输入举报原因", "评论存在风险");
  if (!detail) {
    return null;
  }
  const data = await request(
    `/articles/${encodeURIComponent(state.selectedArticle.slug)}/comments/${encodeURIComponent(commentId)}/report`,
    {
      method: "POST",
      body: JSON.stringify({
        report: {
          reason: detail.slice(0, 80),
          detail,
        },
      }),
    },
  );
  toast("举报已提交");
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function normalizeArticleResult(item) {
  return item?.article || item;
}

function updateArticleInCollections(updatedArticle) {
  const replaceBySlug = (items) =>
    items.map((item) => (item.slug === updatedArticle.slug ? updatedArticle : item));
  state.articles = replaceBySlug(state.articles);
  const updatedFavorites = replaceBySlug(state.favoriteArticles).filter(
    (item) => item.favorited,
  );
  if (
    updatedArticle.favorited &&
    !updatedFavorites.some((item) => item.slug === updatedArticle.slug)
  ) {
    updatedFavorites.unshift(updatedArticle);
  }
  state.favoriteArticles = updatedFavorites;
  state.recommendations = state.recommendations.map((item) =>
    item.article?.slug === updatedArticle.slug
      ? { ...item, article: updatedArticle }
      : item,
  );
  state.recommendationPool = state.recommendationPool.map((item) =>
    item.article?.slug === updatedArticle.slug
      ? { ...item, article: updatedArticle }
      : item,
  );
  if (state.selectedArticle?.slug === updatedArticle.slug) {
    state.selectedArticle = updatedArticle;
  }
}

async function toggleFavoriteArticle(slug) {
  const current =
    state.selectedArticle?.slug === slug
      ? state.selectedArticle
      : state.articles.find((item) => item.slug === slug) ||
        state.favoriteArticles.find((item) => item.slug === slug);
  if (!current) {
    throw new Error("未找到文章。");
  }
  const method = current.favorited ? "DELETE" : "POST";
  const data = await request(`/articles/${encodeURIComponent(slug)}/favorite`, {
    method,
  });
  const updatedArticle = data.article;
  updateArticleInCollections(updatedArticle);
  renderArticles({ articles: state.articles });
  if (state.selectedArticle?.slug === slug) {
    renderArticle(updatedArticle);
  }
  if (document.body.classList.contains("is-authenticated")) {
    renderFavoriteArticles({ articles: state.favoriteArticles });
  }
  toast(updatedArticle.favorited ? "已加入收藏" : "已取消收藏");
  return updatedArticle;
}

async function toggleCommentLike(commentId) {
  if (!state.selectedArticle) {
    throw new Error("请先选择一篇文章。");
  }
  const current = state.comments.find((item) => String(item.id) === String(commentId));
  if (!current) {
    throw new Error("未找到评论。");
  }
  const method = current.liked ? "DELETE" : "POST";
  await request(
    `/articles/${encodeURIComponent(state.selectedArticle.slug)}/comments/${encodeURIComponent(commentId)}/like`,
    {
      method,
    },
  );
  await loadComments();
  toast(current.liked ? "已取消点赞" : "已点赞评论");
}

function searchExplanation(article, query) {
  const lowered = String(query || "").trim().toLowerCase();
  if (!lowered) {
    return "";
  }
  const matchedTags = (article.tagList || []).filter((tag) =>
    String(tag).toLowerCase().includes(lowered),
  );
  if (matchedTags.length) {
    return `标签包含 ${matchedTags.slice(0, 2).join("、")}`;
  }
  if (String(article.title || "").toLowerCase().includes(lowered)) {
    return "标题命中搜索词";
  }
  if (String(article.description || "").toLowerCase().includes(lowered)) {
    return "摘要命中搜索词";
  }
  return "正文与搜索词相关";
}

function openContentEditModal(kind, itemId) {
  state.editingContent = { kind, itemId };
  if (kind === "article") {
    const article = state.userContent.articles.find((item) => item.slug === itemId);
    if (!article) {
      toast("未找到文章内容", "error");
      return;
    }
    $("contentEditTitle").textContent = "编辑文章";
    $("contentEditHint").textContent = "可先保存修改，必要时再重新提交审核。";
    $("contentEditFields").innerHTML = `
      <label>标题<input id="contentEditArticleTitle" value="${escapeHtml(article.title)}" /></label>
      <label>摘要<input id="contentEditArticleDescription" value="${escapeHtml(article.description || "")}" /></label>
      <label>标签<input id="contentEditArticleTags" value="${escapeHtml((article.tagList || []).join(","))}" /></label>
      <label>正文<textarea id="contentEditArticleBody" rows="12">${escapeHtml(article.body || "")}</textarea></label>
    `;
  } else {
    const comment = state.userContent.comments.find((item) => String(item.id) === String(itemId));
    if (!comment) {
      toast("未找到评论内容", "error");
      return;
    }
    $("contentEditTitle").textContent = "编辑评论";
    $("contentEditHint").textContent = "修改评论内容后可重新提交审核。";
    $("contentEditFields").innerHTML = `
      <section class="detail-section">
        <p class="eyebrow">文章</p>
        <p>${escapeHtml(comment.articleTitle || comment.articleSlug)}</p>
      </section>
      <label>评论内容<textarea id="contentEditCommentBody" rows="10">${escapeHtml(comment.body || "")}</textarea></label>
    `;
  }
  $("contentEditModal").classList.remove("hidden");
  syncModalState();
}

function closeContentEditModal() {
  $("contentEditModal").classList.add("hidden");
  $("contentEditFields").innerHTML = "";
  state.editingContent = null;
  syncModalState();
}

function editArticlePayload(submitForReview = false) {
  return {
    article: {
      title: $("contentEditArticleTitle").value.trim(),
      description: $("contentEditArticleDescription").value.trim(),
      body: $("contentEditArticleBody").value.trim(),
      tagList: $("contentEditArticleTags")
        .value.split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
      submitForReview,
    },
  };
}

function editCommentPayload(submitForReview = false) {
  return {
    comment: {
      body: $("contentEditCommentBody").value.trim(),
      submitForReview,
    },
  };
}

function stableHash(value) {
  return String(value || "").split("").reduce((total, char) => {
    return (total * 31 + char.charCodeAt(0)) >>> 0;
  }, 7);
}

function coverForArticle(article) {
  const key = `${article.slug || ""}${article.title || ""}`;
  return coverImages[stableHash(key) % coverImages.length];
}

function readingTime(body) {
  const words = String(body || "").trim().split(/\s+/).filter(Boolean).length;
  return Math.max(1, Math.round(words / 220));
}

function formatDate(value) {
  if (!value) {
    return "unknown date";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function excerpt(value, length = 140) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= length) {
    return text;
  }
  return `${text.slice(0, length - 1)}...`;
}

document.querySelectorAll(".nav-item").forEach((item) => {
  item.addEventListener("click", () => switchView(item.dataset.view));
});

document.querySelectorAll("[data-auth-mode]").forEach((tab) => {
  tab.addEventListener("click", () => setAuthMode(tab.dataset.authMode));
});

$("authSubmitBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    const path = state.authMode === "register" ? "/users" : "/users/login";
    const user = {
      email: $("email").value.trim(),
      password: $("password").value,
    };
    if (state.authMode === "register") {
      user.username = $("username").value.trim();
    }
    const data = await request(path, {
      method: "POST",
      body: JSON.stringify({ user }),
    });
    setToken(data.user.token, data.user);
    toast(`${state.authMode === "register" ? "注册" : "登录"}成功`);
    switchView("feedView");
    await loadArticles();
  }).catch((error) => toast(error.message, "error"));
});

$("logoutBtn").addEventListener("click", () => {
  setToken("", null);
  closeArticleLibraryDrawer();
  switchView("feedView");
  toast("已退出");
});

$("articleLibraryToggleBtn").addEventListener("click", openArticleLibraryDrawer);
$("articleLibraryDrawerCloseBtn").addEventListener("click", closeArticleLibraryDrawer);

$("articleLibraryDrawer").addEventListener("click", (event) => {
  if (event.target === $("articleLibraryDrawer")) {
    closeArticleLibraryDrawer();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }
  if (!$("articleLibraryDrawer").classList.contains("hidden")) {
    closeArticleLibraryDrawer();
  }
});

$("loadArticlesBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, () => loadArticles({ reset: true })).catch(
    (error) => toast(error.message, "error"),
  );
});

$("filterQuery").addEventListener("keydown", async (event) => {
  if (event.key !== "Enter") {
    return;
  }
  await loadArticles({ reset: true }).catch((error) => toast(error.message, "error"));
});

$("askArticleLibraryBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, () =>
    askArticleLibrary($("articleLibraryQuestion").value),
  ).catch((error) => {
    renderArticleLibraryError(error.message);
    toast(error.message, "error");
  });
});

$("articleLibraryQuestion").addEventListener("keydown", async (event) => {
  if (event.key !== "Enter" || event.shiftKey) {
    return;
  }
  event.preventDefault();
  await withBusy($("askArticleLibraryBtn"), () =>
    askArticleLibrary($("articleLibraryQuestion").value),
  ).catch((error) => {
    renderArticleLibraryError(error.message);
    toast(error.message, "error");
  });
});

$("articleLibraryAnswer").addEventListener("click", async (event) => {
  const followup = event.target.closest("[data-qa-followup]");
  if (followup) {
    $("articleLibraryQuestion").value = followup.dataset.qaFollowup || "";
    await withBusy($("askArticleLibraryBtn"), () =>
      askArticleLibrary($("articleLibraryQuestion").value),
    ).catch((error) => {
      renderArticleLibraryError(error.message);
      toast(error.message, "error");
    });
    return;
  }

  const sourceButton = event.target.closest("[data-qa-source-index]");
  if (!sourceButton) {
    return;
  }
  const source = state.articleLibrarySources[Number(sourceButton.dataset.qaSourceIndex)];
  const article = normalizeArticleResult(source?.article);
  if (!article?.slug) {
    return;
  }
  const data = await request(`/articles/${encodeURIComponent(article.slug)}`);
  renderArticle(data.article);
  closeArticleLibraryDrawer();
  switchView("readerView");
});

$("articlePager").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-article-page]");
  if (!button) {
    return;
  }
  const direction = button.dataset.articlePage;
  state.articlePage.offset = Math.max(
    0,
    state.articlePage.offset +
      (direction === "next" ? state.articlePage.limit : -state.articlePage.limit),
  );
  await loadArticles().catch((error) => toast(error.message, "error"));
});

$("articleGrid").addEventListener("click", async (event) => {
  const favoriteButton = event.target.closest("[data-toggle-favorite]");
  if (favoriteButton) {
    event.preventDefault();
    event.stopPropagation();
    await withBusy(favoriteButton, () =>
      toggleFavoriteArticle(favoriteButton.dataset.toggleFavorite),
    ).catch((error) => toast(error.message, "error"));
    return;
  }
  const card = event.target.closest(".article-card");
  if (!card?.dataset.slug) {
    return;
  }
  const data = await request(`/articles/${encodeURIComponent(card.dataset.slug)}`);
  renderArticle(data.article);
  switchView("readerView");
});

$("readerArticle").addEventListener("click", async (event) => {
  const favoriteButton = event.target.closest("[data-toggle-favorite]");
  if (favoriteButton) {
    await withBusy(favoriteButton, () =>
      toggleFavoriteArticle(favoriteButton.dataset.toggleFavorite),
    ).catch((error) => toast(error.message, "error"));
    return;
  }
  const button = event.target.closest("[data-report-article]");
  if (!button) {
    return;
  }
  await withBusy(button, () => reportArticle(button.dataset.reportArticle)).catch(
    (error) => toast(error.message, "error"),
  );
});

$("recommendationsList").addEventListener("click", (event) => {
  const item = event.target.closest(".recommendation-item");
  if (!item) {
    return;
  }
  const recommendation = state.recommendations[Number(item.dataset.index)];
  if (recommendation?.article) {
    renderArticle(recommendation.article);
    switchView("readerView");
  }
});

$("analyzeBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    renderAnalysisLoading();
    const data = await request("/articles/ai/analyze", {
      method: "POST",
      body: JSON.stringify(articlePayload()),
      timeoutMs: ANALYSIS_TIMEOUT_MS,
      timeoutMessage: "分析耗时较长，请确认后端 AI 服务已经启动后重试。",
    });
    renderAnalysis(data);
    toast("草稿分析完成");
  }).catch((error) => {
    renderAnalysisError(error.message);
    toast(error.message, "error");
  });
});

if ($("analysisResult")) {
  $("analysisResult").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-revise-suggestion]");
    if (!button) {
      return;
    }
    const suggestion = button.dataset.reviseSuggestion || "";
    await withBusy(button, async () => {
      renderSuggestionRevisionLoading(suggestion);
      const data = await request("/articles/ai/revise-suggestion", {
        method: "POST",
        body: JSON.stringify({ ...articlePayload(), suggestion }),
        timeoutMs: REVISION_TIMEOUT_MS,
        timeoutMessage: "AI 改写耗时较长，请确认后端 AI 服务已经启动后重试。",
      });
      renderSuggestionRevision(data);
      toast("建议改写完成");
    }).catch((error) => {
      renderPolishError(error.message);
      toast(error.message, "error");
    });
  });
}

if ($("polishBtn")) {
  $("polishBtn").addEventListener("click", async (event) => {
    await withBusy(event.currentTarget, async () => {
      const body = $("articleBody").value.trim();
      if (!body) {
        throw new Error("正文不能为空。");
      }
      const instruction = $("polishInstruction").value.trim() || "使语言更简洁，提升表达流畅度";
      renderPolishLoading(instruction);
      const data = await request("/articles/ai/polish", {
        method: "POST",
        body: JSON.stringify({ body, instruction }),
        timeoutMs: POLISH_TIMEOUT_MS,
        timeoutMessage: "AI 润色耗时较长，请确认后端 AI 服务已经启动后重试。",
      });
      renderPolish(data);
      toast("润色完成");
    }).catch((error) => {
      renderPolishError(error.message);
      toast(error.message, "error");
    });
  });
}

if ($("polishResult")) {
  $("polishResult").addEventListener("click", (event) => {
    const button = event.target.closest("#applyPolishBtn");
    if (!button || !state.polishResult) {
      return;
    }
    saveDraft("AI 替换前原版");
    $("articleBody").value = state.polishResult;
    resetPolish();
    toast("已替换正文，原版已保存到草稿版本");
  });
}

$("publishBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    saveDraft("发布前");
    const data = await request("/articles", {
      method: "POST",
      body: JSON.stringify(articlePayload()),
    });
    clearDrafts({ clearEditor: true });
    await loadArticles();
    renderArticle(data.article);
    switchView("readerView");
    if ((data.article.contentStatus || "visible") === "pending") {
      toast("文章已进入待审核，通过后会公开显示");
      return;
    }
    toast("文章已发布");
  }).catch((error) => {
    renderArticleRejection(error.payload);
    toast(error.message, "error");
  });
});

$("saveDraftBtn").addEventListener("click", () => {
  saveDraft("手动保存");
  toast("草稿已保存");
});

$("editorView").addEventListener("click", (event) => {
  const button = event.target.closest("#clearDraftsBtn");
  if (!button) {
    return;
  }
  event.preventDefault();
  clearDrafts({ clearEditor: true });
  toast("草稿已清空");
});

$("draftVersions").addEventListener("click", (event) => {
  const item = event.target.closest("[data-draft-id]");
  if (!item) {
    return;
  }
  restoreDraft(item.dataset.draftId);
});

$("commentsPager").addEventListener("click", (event) => {
  const button = event.target.closest("[data-comment-page]");
  if (!button) {
    return;
  }
  const direction = button.dataset.commentPage;
  state.commentPage.page = Math.max(
    0,
    state.commentPage.page + (direction === "next" ? 1 : -1),
  );
  renderCommentPage();
});

$("commentsList").addEventListener("click", async (event) => {
  const likeButton = event.target.closest("[data-toggle-comment-like]");
  if (likeButton) {
    await withBusy(likeButton, () =>
      toggleCommentLike(likeButton.dataset.toggleCommentLike),
    ).catch((error) => toast(error.message, "error"));
    return;
  }
  const button = event.target.closest("[data-report-comment]");
  if (!button) {
    return;
  }
  await withBusy(button, () => reportComment(button.dataset.reportComment)).catch(
    (error) => toast(error.message, "error"),
  );
});

$("loadNotificationsBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, loadNotifications).catch((error) =>
    toast(error.message, "error"),
  );
});

$("loadFavoriteArticlesBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, loadFavoriteArticles).catch((error) =>
    toast(error.message, "error"),
  );
});

$("loadUserContentBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, loadUserContent).catch((error) =>
    toast(error.message, "error"),
  );
});

$("profileView").addEventListener("click", (event) => {
  const typeButton = event.target.closest("[data-notification-filter]");
  if (typeButton) {
    event.preventDefault();
    setNotificationFilter(typeButton.dataset.notificationFilter);
    return;
  }
  const stateButton = event.target.closest("[data-notification-read-filter]");
  if (stateButton) {
    event.preventDefault();
    setNotificationReadFilter(stateButton.dataset.notificationReadFilter);
    return;
  }
  const contentTabButton = event.target.closest("[data-user-content-tab]");
  if (contentTabButton) {
    event.preventDefault();
    setUserContentTab(contentTabButton.dataset.userContentTab);
    $("userContentStatus").value = userContentFilterState().status;
    $("userContentQuery").value = userContentFilterState().q;
    return;
  }
  const pagerButton = event.target.closest("[data-user-content-page]");
  if (pagerButton) {
    event.preventDefault();
    const delta = pagerButton.dataset.userContentPage === "next" ? 1 : -1;
    userContentFilterState().page = Math.max(0, userContentFilterState().page + delta);
    loadUserContent().catch((error) => toast(error.message, "error"));
  }
});

$("userContentStatus").addEventListener("change", () => {
  userContentFilterState().status = $("userContentStatus").value;
  userContentFilterState().page = 0;
  loadUserContent().catch((error) => toast(error.message, "error"));
});

$("userContentQuery").addEventListener("keydown", (event) => {
  if (event.key !== "Enter") {
    return;
  }
  userContentFilterState().q = $("userContentQuery").value.trim();
  userContentFilterState().page = 0;
  loadUserContent().catch((error) => toast(error.message, "error"));
});

$("notificationsList").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-read-notification]");
  if (!button) {
    return;
  }
  await withBusy(button, async () => {
    await request(`/user/notifications/${encodeURIComponent(button.dataset.readNotification)}/read`, {
      method: "PUT",
    });
    await loadNotifications();
  }).catch((error) => toast(error.message, "error"));
});

$("favoriteArticlesList").addEventListener("click", async (event) => {
  const favoriteButton = event.target.closest("[data-toggle-favorite]");
  if (favoriteButton) {
    await withBusy(favoriteButton, () =>
      toggleFavoriteArticle(favoriteButton.dataset.toggleFavorite),
    ).catch((error) => toast(error.message, "error"));
    return;
  }
  const row = event.target.closest("[data-favorite-slug]");
  if (!row) {
    return;
  }
  const article = state.favoriteArticles.find((item) => item.slug === row.dataset.favoriteSlug);
  if (!article) {
    return;
  }
  renderArticle(article);
  switchView("readerView");
});

$("userContentList").addEventListener("click", async (event) => {
  const editArticleButton = event.target.closest("[data-edit-user-article]");
  if (editArticleButton) {
    openContentEditModal("article", editArticleButton.dataset.editUserArticle);
    return;
  }
  const editCommentButton = event.target.closest("[data-edit-user-comment]");
  if (editCommentButton) {
    openContentEditModal("comment", editCommentButton.dataset.editUserComment);
    return;
  }
  const resubmitArticleButton = event.target.closest("[data-resubmit-article]");
  if (resubmitArticleButton) {
    await withBusy(resubmitArticleButton, async () => {
      const article = state.userContent.articles.find(
        (item) => item.slug === resubmitArticleButton.dataset.resubmitArticle,
      );
      if (!article) {
        throw new Error("未找到文章。");
      }
      await request(`/articles/${encodeURIComponent(article.slug)}`, {
        method: "PUT",
        body: JSON.stringify({
          article: {
            title: article.title,
            description: article.description,
            body: article.body,
            tagList: article.tagList || [],
            submitForReview: true,
          },
        }),
      });
      await loadUserContent();
      toast("文章已重新提交审核");
    }).catch((error) => toast(error.message, "error"));
    return;
  }
  const resubmitCommentButton = event.target.closest("[data-resubmit-comment]");
  if (!resubmitCommentButton) {
    return;
  }
  await withBusy(resubmitCommentButton, async () => {
    const comment = state.userContent.comments.find(
      (item) => String(item.id) === String(resubmitCommentButton.dataset.resubmitComment),
    );
    if (!comment) {
      throw new Error("未找到评论。");
    }
    await request(
      `/articles/${encodeURIComponent(comment.articleSlug)}/comments/${encodeURIComponent(comment.id)}`,
      {
        method: "PUT",
        body: JSON.stringify({
          comment: {
            body: comment.body,
            submitForReview: true,
          },
        }),
      },
    );
    await loadUserContent();
    toast("评论已重新提交审核");
  }).catch((error) => toast(error.message, "error"));
});

$("contentEditCloseBtn").addEventListener("click", closeContentEditModal);

$("contentEditModal").addEventListener("click", (event) => {
  if (event.target === $("contentEditModal")) {
    closeContentEditModal();
  }
});

$("contentEditSaveBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    if (!state.editingContent) {
      return;
    }
    if (state.editingContent.kind === "article") {
      await request(`/articles/${encodeURIComponent(state.editingContent.itemId)}`, {
        method: "PUT",
        body: JSON.stringify(editArticlePayload(false)),
      });
    } else {
      const comment = state.userContent.comments.find(
        (item) => String(item.id) === String(state.editingContent.itemId),
      );
      if (!comment) {
        throw new Error("未找到评论。");
      }
      await request(
        `/articles/${encodeURIComponent(comment.articleSlug)}/comments/${encodeURIComponent(comment.id)}`,
        {
          method: "PUT",
          body: JSON.stringify(editCommentPayload(false)),
        },
      );
    }
    await loadUserContent();
    closeContentEditModal();
    toast("内容已保存");
  }).catch((error) => toast(error.message, "error"));
});

$("contentEditSubmitBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    if (!state.editingContent) {
      return;
    }
    if (state.editingContent.kind === "article") {
      await request(`/articles/${encodeURIComponent(state.editingContent.itemId)}`, {
        method: "PUT",
        body: JSON.stringify(editArticlePayload(true)),
      });
    } else {
      const comment = state.userContent.comments.find(
        (item) => String(item.id) === String(state.editingContent.itemId),
      );
      if (!comment) {
        throw new Error("未找到评论。");
      }
      await request(
        `/articles/${encodeURIComponent(comment.articleSlug)}/comments/${encodeURIComponent(comment.id)}`,
        {
          method: "PUT",
          body: JSON.stringify(editCommentPayload(true)),
        },
      );
    }
    await loadUserContent();
    closeContentEditModal();
    toast("内容已重新提交审核");
  }).catch((error) => toast(error.message, "error"));
});

$("commentBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    if (!state.selectedArticle) {
      throw new Error("请先选择一篇文章。");
    }
    const data = await request(`/articles/${encodeURIComponent(state.selectedArticle.slug)}/comments`, {
      method: "POST",
      body: JSON.stringify({
        comment: {
          body: $("commentBody").value.trim(),
        },
      }),
    });
    $("commentBody").value = "";
    await loadComments();
    $("moderationResult").className = "moderation-empty";
    if ((data.comment.contentStatus || "visible") === "pending") {
      $("moderationResult").textContent = "评论已进入待审核，通过后会显示。";
      toast("评论已提交审核");
      return;
    }
    $("moderationResult").textContent = "审核通过，评论已发布。";
    toast("评论已发布");
  }).catch((error) => {
    if (error.payload?.moderation) {
      renderModeration(error.payload.moderation);
    }
    toast(error.message, "error");
  });
});

$("loadRecommendationsBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    if (!state.selectedArticle) {
      throw new Error("请先选择一篇文章。");
    }
    await loadRecommendations();
    toast("相关推荐已刷新");
  }).catch((error) => toast(error.message, "error"));
});

$("rotateRecommendationsBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    if (!state.selectedArticle) {
      throw new Error("请先选择一篇文章。");
    }
    if (state.recommendationPool.length <= 5) {
      await loadRecommendations(state.selectedArticle.slug, { silent: true });
    }
    rotateRecommendations();
    toast("已换一批推荐");
  }).catch((error) => toast(error.message, "error"));
});

setAuthMode("login");
renderAccount();
renderDrafts();
resetAnalysis();
resetPolish();
setNotificationFilter(state.notificationFilter, { render: false });
switchView("feedView");
loadArticles().catch((error) => toast(error.message, "error"));
