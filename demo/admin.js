const state = {
  token: localStorage.getItem("conduitToken") || "",
  user: JSON.parse(localStorage.getItem("conduitUser") || "null"),
  authMode: "login",
  activeView: "overviewView",
  loadedViews: {},
  moderation: {
    comments: { status: "pending", q: "", limit: 12, offset: 0 },
    articles: { status: "pending", q: "", limit: 12, offset: 0 },
  },
  articles: { status: "visible", limit: 12, offset: 0 },
  articleItems: [],
  articleDetailCache: {},
  articleModalSlug: "",
  comments: { status: "visible", mode: "threads", limit: 12, offset: 0 },
  reports: { status: "pending", type: "all", limit: 12, offset: 0 },
  audit: { type: "all", limit: 12, offset: 0 },
  selections: {
    articleModeration: new Set(),
    commentModeration: new Set(),
    reports: new Set(),
  },
  expandedCommentThreads: new Set(),
};

const $ = (id) => document.getElementById(id);
const query = (selector) => document.querySelector(selector);
const API_BASE =
  window.API_BASE ||
  localStorage.getItem("conduitApiBase") ||
  `${window.location.protocol === "file:" ? "http:" : window.location.protocol}//${
    window.location.hostname || "127.0.0.1"
  }:8010/api`;
const REQUEST_TIMEOUT_MS = 12000;

const titles = {
  overviewView: ["平台态势", "总览看板"],
  moderationView: ["复核队列", "人工审核"],
  reportsView: ["申诉裁定", "举报处置"],
  auditView: ["处理轨迹", "审计记录"],
  articlesView: ["文章库维护", "文章维护"],
  commentsView: ["评论区维护", "评论维护"],
};

let noteModalResolver = null;

function headers() {
  return {
    "Content-Type": "application/json",
    ...(state.token ? { Authorization: `Token ${state.token}` } : {}),
  };
}

async function request(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    signal: controller.signal,
    headers: {
      ...headers(),
      ...(options.headers || {}),
    },
  }).catch((error) => {
    if (error.name === "AbortError") {
      throw new Error("请求超时，请确认后端服务已经启动。");
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
  const hasOpenModal =
    !$("noteModal").classList.contains("hidden") || !$("articleModal").classList.contains("hidden");
  document.body.classList.toggle("modal-open", hasOpenModal);
}

function requestNote(
  title,
  {
    defaultValue = "",
    description = "请输入本次处理的说明，只有确认后才会执行。",
    confirmLabel = "确认",
    placeholder = "输入这次处理的原因或依据",
    tone = "default",
  } = {},
) {
  if (noteModalResolver) {
    closeNoteModal({ confirmed: false, note: "" });
  }
  $("noteModalTitle").textContent = title;
  $("noteModalHint").textContent = description;
  $("noteModalInput").value = defaultValue;
  $("noteModalInput").placeholder = placeholder;
  $("noteModalConfirmBtn").textContent = confirmLabel;
  $("noteModalConfirmBtn").classList.toggle("danger-button", tone === "danger");
  $("noteModal").dataset.tone = tone;
  $("noteModal").classList.remove("hidden");
  syncModalState();
  $("noteModalInput").focus();
  return new Promise((resolve) => {
    noteModalResolver = resolve;
  });
}

function closeNoteModal(result) {
  $("noteModal").classList.add("hidden");
  $("noteModal").dataset.tone = "default";
  $("noteModalConfirmBtn").textContent = "确认";
  $("noteModalConfirmBtn").classList.remove("danger-button");
  $("noteModalInput").value = "";
  const resolver = noteModalResolver;
  noteModalResolver = null;
  syncModalState();
  if (resolver) {
    resolver(result);
  }
}

async function loadArticleDetail(slug) {
  const cached = state.articleDetailCache[slug];
  if (cached) {
    return cached;
  }
  const data = await request(`/admin/articles/${encodeURIComponent(slug)}`);
  state.articleDetailCache[slug] = data.article;
  return data.article;
}

async function openArticleModal(slug) {
  state.articleModalSlug = slug;
  const preview = state.articleItems.find((item) => item.slug === slug);
  $("articleModalTitle").textContent = preview?.title || "文章详情";
  $("articleModalBody").innerHTML = `
    <div class="detail-loading">
      <p class="eyebrow">Loading</p>
      <p class="muted">正在加载完整文章信息...</p>
    </div>
  `;
  $("articleModalComments").innerHTML = `<div class="comment"><p class="muted">正在加载评论线程...</p></div>`;
  $("articleModal").classList.remove("hidden");
  syncModalState();
  try {
    const [article, comments] = await Promise.all([
      loadArticleDetail(slug),
      loadArticleCommentsForAdmin(slug),
    ]);
    if ($("articleModal").classList.contains("hidden")) {
      return;
    }
    $("articleModalTitle").textContent = article.title || "未命名文章";
    $("articleModalBody").innerHTML = renderArticleDetail(article);
    $("articleModalComments").innerHTML = renderArticleThreadComments(comments);
  } catch (error) {
    $("articleModalBody").innerHTML = `
      <div class="detail-loading">
        <p class="eyebrow">Error</p>
        <p class="muted">${escapeHtml(error.message || "文章详情加载失败。")}</p>
      </div>
    `;
    $("articleModalComments").innerHTML = `<div class="comment"><p class="muted">评论线程加载失败。</p></div>`;
    toast(error.message || "文章详情加载失败。", "error");
  }
}

function closeArticleModal() {
  $("articleModal").classList.add("hidden");
  $("articleModalComments").innerHTML = "";
  state.articleModalSlug = "";
  syncModalState();
}

function renderArticleDetail(article) {
  const tags = article.tagList || [];
  return `
    <div class="article-detail-summary">
      <div class="article-detail-head">
        <span class="status-pill ${escapeHtml(article.contentStatus || "visible")}">${escapeHtml(
          contentStatusLabel(article.contentStatus || "visible"),
        )}</span>
        <h3>${escapeHtml(article.title || "未命名文章")}</h3>
      </div>
      <div class="meta">
        <span>作者：${escapeHtml(article.author?.username || "unknown")}</span>
        <span>创建于 ${formatDate(article.createdAt)}</span>
        <span>更新于 ${formatDate(article.updatedAt)}</span>
        <span>收藏 ${Number(article.favoritesCount || 0)}</span>
      </div>
    </div>
    <section class="detail-section">
      <p class="eyebrow">Slug</p>
      <p>${escapeHtml(article.slug)}</p>
    </section>
    <section class="detail-section">
      <p class="eyebrow">摘要</p>
      <p>${escapeHtml(article.description || "无摘要")}</p>
    </section>
    <section class="detail-section">
      <p class="eyebrow">标签</p>
      <div class="tags">
        ${
          tags.length
            ? tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")
            : `<span class="tag">无标签</span>`
        }
      </div>
    </section>
    <section class="detail-section">
      <p class="eyebrow">正文</p>
      <div class="body">${escapeHtml(article.body || "")}</div>
    </section>
  `;
}

async function loadArticleCommentsForAdmin(slug) {
  const data = await request(`/admin/articles/${encodeURIComponent(slug)}/comments?status=all&limit=50&offset=0`);
  return data.comments || [];
}

function renderArticleThreadComments(comments) {
  if (!comments.length) {
    return `<div class="comment"><p class="muted">这篇文章下暂无评论。</p></div>`;
  }
  return comments
    .map(
      (comment) => `
        <article class="admin-row" data-id="${comment.id}">
          <div>
            <p>${escapeHtml(comment.body)}</p>
            <div class="meta">
              <span class="status-pill ${escapeHtml(comment.contentStatus || "visible")}">${escapeHtml(
                contentStatusLabel(comment.contentStatus || "visible"),
              )}</span>
              <span>#${comment.id}</span>
              <span>${escapeHtml(comment.authorUsername || "unknown")}</span>
              <span>${formatDate(comment.createdAt)}</span>
            </div>
          </div>
          <div class="actions">
            ${commentStatusActions(comment)}
          </div>
        </article>
      `,
    )
    .join("");
}

async function toggleCommentThread(slug) {
  const key = String(slug);
  if (state.expandedCommentThreads.has(key)) {
    state.expandedCommentThreads.delete(key);
    await loadComments();
    return;
  }
  state.expandedCommentThreads.add(key);
  await loadComments();
  const target = query(`#thread-inline-${CSS.escape(key)}`);
  if (!target) {
    return;
  }
  const comments = await loadArticleCommentsForAdmin(slug);
  target.innerHTML = renderArticleThreadComments(comments);
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
  $("adminAccountName").textContent = name;
  $("adminLogoutBtn").classList.toggle("hidden", !state.token);
  $("adminAuthView").classList.toggle("active", !state.token);
  document.body.classList.toggle("is-authenticated", Boolean(state.token));
}

function switchView(viewId, options = {}) {
  const shouldLoad = options.load !== false;
  state.activeView = viewId;
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view.id === viewId);
  });
  document.querySelectorAll("[data-admin-view]").forEach((item) => {
    item.classList.toggle("active", item.dataset.adminView === viewId);
  });
  const [eyebrow, title] = titles[viewId];
  $("adminEyebrow").textContent = eyebrow;
  $("adminViewTitle").textContent = title;
  if (shouldLoad && state.token) {
    loadViewData(viewId).catch((error) => toast(error.message, "error"));
  }
}

function setAuthMode(mode) {
  state.authMode = mode;
  document.querySelectorAll("[data-admin-auth-mode]").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.adminAuthMode === mode);
  });
  $("adminUsernameField").classList.toggle("hidden", mode !== "register");
  $("adminAuthSubmitBtn").textContent = mode === "register" ? "注册" : "登录";
  $("adminAuthHint").textContent =
    mode === "register" ? "注册用户名为 admin 的账号后可进入后台。" : "使用管理员账号进入后台。";
}

function statCard(label, value, icon = "metric") {
  return `
    <div class="stat-card stat-card-metric">
      <span class="stat-icon ${escapeHtml(icon)}" aria-hidden="true"></span>
      <span>${escapeHtml(label)}</span>
      <strong>${Number(value || 0)}</strong>
    </div>
  `;
}

function renderOverview(data) {
  const stats = data?.stats || {};
  const moderationTotal =
    Number(stats.moderationTotal || 0) + Number(stats.articleModerationTotal || 0);
  const moderationPending =
    Number(stats.moderationPending || 0) + Number(stats.articleModerationPending || 0);
  const moderationBlocked =
    Number(stats.moderationBlocked || 0) + Number(stats.articleModerationBlocked || 0);
  $("overviewStats").innerHTML = [
    statCard("用户", stats.usersCount, "icon-users"),
    statCard("文章", stats.articlesCount, "icon-article"),
    statCard("评论", stats.commentsCount, "icon-comment"),
    statCard("审核记录", moderationTotal, "icon-review"),
    statCard("待复核", moderationPending, "icon-pending"),
    statCard("已拦截", moderationBlocked, "icon-blocked"),
    statCard("高风险", stats.highRisk, "icon-risk"),
  ].join("");
  renderContentScaleChart(stats);
  renderModerationStatusChart({
    ...stats,
    moderationTotal,
    moderationPending,
    moderationBlocked,
  });
}

function renderModeration(data) {
  renderModerationStats(data?.comments, data?.articles);
  renderModerationQueue("comment", data?.comments || {});
  renderModerationQueue("article", data?.articles || {});
}

function renderModerationStats(commentData, articleData) {
  const commentStats = commentData?.stats || {};
  const articleStats = articleData?.stats || {};
  const stats = {
    total: Number(commentStats.total || 0) + Number(articleStats.total || 0),
    blocked: Number(commentStats.blocked || 0) + Number(articleStats.blocked || 0),
    pending: Number(commentStats.pending || 0) + Number(articleStats.pending || 0),
    highRisk: Number(commentStats.highRisk || 0) + Number(articleStats.highRisk || 0),
  };
  $("moderationStats").innerHTML = [
    statCard("总审核", stats.total, "icon-review"),
    statCard("已拦截", stats.blocked, "icon-blocked"),
    statCard("待复核", stats.pending, "icon-pending"),
    statCard("高风险", stats.highRisk, "icon-risk"),
  ].join("");
}

function renderModerationQueue(kind, data) {
  const target = kind === "article" ? $("articleModerationQueue") : $("commentModerationQueue");
  const pagerTarget =
    kind === "article" ? $("articleModerationPager") : $("commentModerationPager");
  const items = data?.items || [];
  if (!items.length) {
    target.innerHTML = `<div class="comment"><p class="muted">暂无内容。</p></div>`;
    renderAdminPager(
      pagerTarget,
      state.moderation[kind === "article" ? "articles" : "comments"],
      data?.itemsCount || 0,
      kind === "article" ? "article-moderation" : "comment-moderation",
    );
    return;
  }
  target.innerHTML = items
    .map(
      (item) => `
        <article class="review-item" data-id="${item.id}">
          <div class="review-head">
            <label class="select-row">
              <input
                type="checkbox"
                data-select-scope="${kind === "article" ? "articleModeration" : "commentModeration"}"
                data-select-id="${item.id}"
                ${state.selections[kind === "article" ? "articleModeration" : "commentModeration"].has(String(item.id)) ? "checked" : ""}
              />
              <span>选中</span>
            </label>
            <span class="status-pill ${escapeHtml(item.reviewStatus)}">
              ${escapeHtml(reviewStatusLabel(item.reviewStatus))}
            </span>
            <span class="status-pill ${escapeHtml(item.contentStatus)}">
              ${escapeHtml(contentStatusLabel(item.contentStatus))}
            </span>
          </div>
          ${
            item.contentType === "article"
              ? `<h3>${escapeHtml(item.title || item.articleTitle || "未命名文章")}</h3>`
              : ""
          }
          <p>${escapeHtml(excerpt(item.body, item.contentType === "article" ? 220 : 180))}</p>
          <p class="muted">${escapeHtml(item.reason || "")}</p>
          <div class="meta">
            <span>${escapeHtml(item.authorUsername || "unknown")}</span>
            <span>${escapeHtml(item.articleTitle || item.articleSlug || item.category)}</span>
            <span>${escapeHtml(item.severity || "risk")}</span>
            ${
              item.contentScore !== null && item.contentScore !== undefined
                ? `<span>${Number(item.contentScore)} 分</span>`
                : ""
            }
          </div>
          <div class="actions">
            ${
              kind === "article" && item.articleSlug
                ? `<button class="ghost" data-article-detail="${escapeHtml(item.articleSlug)}" type="button">查看详情</button>`
                : ""
            }
            ${
              item.reviewStatus === "pending"
                ? `
                  <button class="ghost" data-review-kind="${kind}" data-review-action="approve" data-id="${item.id}" type="button">放行</button>
                  <button class="ghost danger-action" data-review-kind="${kind}" data-review-action="reject" data-id="${item.id}" type="button">驳回</button>
                `
                : ""
            }
          </div>
        </article>
      `,
    )
    .join("");
  renderAdminPager(
    pagerTarget,
    state.moderation[kind === "article" ? "articles" : "comments"],
    data?.itemsCount || 0,
    kind === "article" ? "article-moderation" : "comment-moderation",
  );
}

function renderContentScaleChart(stats) {
  const values = [
    { label: "用户", value: Number(stats.usersCount || 0) },
    { label: "文章", value: Number(stats.articlesCount || 0) },
    { label: "评论", value: Number(stats.commentsCount || 0) },
  ];
  const maxValue = Math.max(1, ...values.map((item) => item.value));
  $("contentScaleChart").innerHTML = values
    .map((item) => {
      const width = Math.max(5, Math.round((item.value / maxValue) * 100));
      return `
        <div class="chart-bar-row">
          <div class="chart-bar-head">
            <span>${escapeHtml(item.label)}</span>
            <strong>${item.value}</strong>
          </div>
          <div class="chart-track">
            <span class="chart-fill" style="width: ${width}%"></span>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderModerationStatusChart(stats) {
  const total = Math.max(1, Number(stats.moderationTotal || 0));
  const values = [
    { label: "待复核", value: Number(stats.moderationPending || 0), tone: "pending" },
    { label: "已拦截", value: Number(stats.moderationBlocked || 0), tone: "blocked" },
    { label: "高风险", value: Number(stats.highRisk || 0), tone: "risk" },
  ];
  $("moderationStatusChart").innerHTML = values
    .map((item) => {
      const percent = Math.min(100, Math.round((item.value / total) * 100));
      return `
        <div class="donut-card ${escapeHtml(item.tone)}">
          <div class="donut" style="--value: ${percent}">
            <span>${percent}%</span>
          </div>
          <div>
            <strong>${escapeHtml(item.label)}</strong>
            <p>${item.value} / ${Number(stats.moderationTotal || 0)}</p>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderArticles(data) {
  const articles = data?.articles || [];
  state.articleItems = articles;
  if (!articles.length) {
    $("adminArticlesList").innerHTML = `<div class="comment"><p class="muted">暂无文章。</p></div>`;
    renderAdminPager($("adminArticlesPager"), state.articles, data?.articlesCount || 0, "articles");
    return;
  }
  $("adminArticlesList").innerHTML = articles
    .map(
      (article) => `
        <article class="admin-row clickable-row" data-slug="${escapeHtml(article.slug)}">
          <div>
            <h3>${escapeHtml(article.title)}</h3>
            <p>${escapeHtml(article.description || excerpt(article.body, 130))}</p>
            <div class="meta">
              <span class="status-pill ${escapeHtml(article.contentStatus || "visible")}">${escapeHtml(
                contentStatusLabel(article.contentStatus || "visible"),
              )}</span>
              <span>${escapeHtml(article.author?.username || "unknown")}</span>
              <span>${formatDate(article.createdAt)}</span>
              <span>${(article.tagList || []).map(escapeHtml).join(", ") || "no tags"}</span>
            </div>
            <p class="row-hint">点击条目可查看完整文章信息</p>
          </div>
          <div class="actions">
            <button class="ghost" data-article-detail="${escapeHtml(article.slug)}" type="button">查看详情</button>
            ${articleStatusActions(article)}
          </div>
        </article>
      `,
    )
    .join("");
  renderAdminPager($("adminArticlesPager"), state.articles, data?.articlesCount || 0, "articles");
}

function renderComments(data) {
  if (state.comments.mode === "threads") {
    return renderCommentThreads(data);
  }
  const comments = data?.comments || [];
  if (!comments.length) {
    $("adminCommentsList").innerHTML = `<div class="comment"><p class="muted">暂无评论。</p></div>`;
    renderAdminPager($("adminCommentsPager"), state.comments, data?.commentsCount || 0, "comments");
    return;
  }
  $("adminCommentsList").innerHTML = comments
    .map(
      (comment) => `
        <article class="admin-row" data-id="${comment.id}">
          <div>
            <p>${escapeHtml(comment.body)}</p>
            <div class="meta">
              <span class="status-pill ${escapeHtml(comment.contentStatus || "visible")}">${escapeHtml(
                contentStatusLabel(comment.contentStatus || "visible"),
              )}</span>
              <span>#${comment.id}</span>
              <span>${escapeHtml(comment.authorUsername || "unknown")}</span>
              <span>${escapeHtml(comment.articleTitle || comment.articleSlug)}</span>
              <span>${formatDate(comment.createdAt)}</span>
            </div>
          </div>
          <div class="actions">
            <button class="ghost" data-article-detail="${escapeHtml(comment.articleSlug)}" type="button">所属文章</button>
            ${commentStatusActions(comment)}
          </div>
        </article>
      `,
    )
    .join("");
  renderAdminPager($("adminCommentsPager"), state.comments, data?.commentsCount || 0, "comments");
}

function renderCommentThreads(data) {
  const threads = data?.threads || [];
  if (!threads.length) {
    $("adminCommentsList").innerHTML = `<div class="comment"><p class="muted">暂无评论线程。</p></div>`;
    renderAdminPager($("adminCommentsPager"), state.comments, data?.threadsCount || 0, "comments");
    return;
  }
  $("adminCommentsList").innerHTML = threads
    .map(
      (thread) => `
        <article class="admin-row thread-row" data-slug="${escapeHtml(thread.articleSlug)}">
          <div>
            <h3>${escapeHtml(thread.articleTitle || thread.articleSlug)}</h3>
            <p>${escapeHtml(excerpt(thread.latestCommentBody || "暂无评论内容", 140))}</p>
            <div class="meta">
              <span class="status-pill ${escapeHtml(thread.articleContentStatus || "visible")}">${escapeHtml(
                contentStatusLabel(thread.articleContentStatus || "visible"),
              )}</span>
              <span>评论 ${Number(thread.commentsCount || 0)}</span>
              <span>显示 ${Number(thread.visibleCount || 0)}</span>
              <span>待审核 ${Number(thread.pendingCount || 0)}</span>
              <span>隐藏 ${Number(thread.hiddenCount || 0)}</span>
              <span>${formatDate(thread.latestCommentAt)}</span>
            </div>
          </div>
          <div class="actions">
            <button
              class="ghost"
              data-toggle-thread="${escapeHtml(thread.articleSlug)}"
              type="button"
            >${state.expandedCommentThreads.has(String(thread.articleSlug)) ? "收起评论" : "展开评论"}</button>
            <button class="ghost" data-article-detail="${escapeHtml(thread.articleSlug)}" type="button">查看文章与评论</button>
          </div>
          ${
            state.expandedCommentThreads.has(String(thread.articleSlug))
              ? `<div class="thread-inline" id="thread-inline-${escapeHtml(thread.articleSlug)}">
                  <div class="comment"><p class="muted">正在加载该文章下的评论...</p></div>
                </div>`
              : ""
          }
        </article>
      `,
    )
    .join("");
  renderAdminPager($("adminCommentsPager"), state.comments, data?.threadsCount || 0, "comments");
}

function renderReports(data) {
  const reports = data?.reports || [];
  if (!reports.length) {
    $("reportsList").innerHTML = `<div class="comment"><p class="muted">暂无举报。</p></div>`;
    renderAdminPager($("reportsPager"), state.reports, data?.reportsCount || 0, "reports");
    return;
  }
  $("reportsList").innerHTML = reports
    .map(
      (report) => `
        <article class="admin-row" data-id="${report.id}">
          <div>
            <h3>${escapeHtml(report.contentType === "article" ? report.articleTitle : `评论举报 #${report.commentId}`)}</h3>
            <p>${escapeHtml(report.detail || report.reason)}</p>
            ${
              report.commentBody
                ? `
                  <div class="content-preview">
                    <span class="preview-label">被举报评论</span>
                    <p>${escapeHtml(excerpt(report.commentBody, 130))}</p>
                  </div>
                `
                : ""
            }
            <div class="meta">
              <span class="status-pill ${escapeHtml(report.status)}">${escapeHtml(reportStatusLabel(report.status))}</span>
              <span class="status-pill ${escapeHtml(report.contentStatus || "visible")}">${escapeHtml(
                contentStatusLabel(report.contentStatus || "visible"),
              )}</span>
              <span>${escapeHtml(report.contentType === "article" ? "文章" : "评论")}</span>
              <span>${escapeHtml(report.reporterUsername || "unknown")}</span>
              <span>${escapeHtml(report.articleTitle || report.articleSlug || "unknown")}</span>
              <span>${formatDate(report.createdAt)}</span>
            </div>
            ${
              report.resolutionNote
                ? `<p class="row-note">处理备注：${escapeHtml(report.resolutionNote)}</p>`
                : ""
            }
          </div>
          <div class="actions">
            <label class="select-row">
              <input
                type="checkbox"
                data-select-scope="reports"
                data-select-id="${report.id}"
                ${state.selections.reports.has(String(report.id)) ? "checked" : ""}
                ${report.status !== "pending" ? "disabled" : ""}
              />
              <span>选中</span>
            </label>
            ${
              report.status === "pending"
                ? `
                  <button class="ghost" data-report-action="ignore" data-report-id="${report.id}" type="button">驳回请求</button>
                  <button class="ghost danger-action" data-report-action="hide" data-report-id="${report.id}" type="button">接受并隐藏</button>
                `
                : ""
            }
          </div>
        </article>
      `,
    )
    .join("");
  renderAdminPager($("reportsPager"), state.reports, data?.reportsCount || 0, "reports");
}

function toggleSelection(scope, id, checked) {
  const bucket = state.selections[scope];
  if (!bucket) {
    return;
  }
  if (checked) {
    bucket.add(String(id));
  } else {
    bucket.delete(String(id));
  }
}

function clearSelection(scope) {
  const bucket = state.selections[scope];
  if (bucket) {
    bucket.clear();
  }
}

function renderAudit(data) {
  const logs = data?.logs || [];
  if (!logs.length) {
    $("auditList").innerHTML = `<div class="comment"><p class="muted">暂无审计记录。</p></div>`;
    renderAdminPager($("auditPager"), state.audit, data?.logsCount || 0, "audit");
    return;
  }
  $("auditList").innerHTML = logs
    .map(
      (log) => `
        <article class="admin-row" data-id="${log.id}">
          <div>
            <h3>${escapeHtml(actionLabel(log.action))}</h3>
            <p>${escapeHtml(log.note || "无备注")}</p>
            ${
              log.commentBody
                ? `
                  <div class="content-preview">
                    <span class="preview-label">评论内容</span>
                    <p>${escapeHtml(excerpt(log.commentBody, 160))}</p>
                  </div>
                `
                : ""
            }
            <div class="meta">
              <span>${escapeHtml(log.contentType === "article" ? "文章" : "评论")}</span>
              <span>${escapeHtml(log.contentType === "comment" ? `评论 #${log.commentId || "-"}` : log.articleTitle || log.articleSlug || "文章")}</span>
              ${
                log.contentType === "comment" && (log.articleTitle || log.articleSlug)
                  ? `<span>${escapeHtml(log.articleTitle || log.articleSlug)}</span>`
                  : ""
              }
              <span>${escapeHtml(log.actorUsername || "system")}</span>
              <span>${escapeHtml(log.fromStatus || "-")} -> ${escapeHtml(log.toStatus || "-")}</span>
              <span>${formatDate(log.createdAt)}</span>
            </div>
          </div>
        </article>
      `,
    )
    .join("");
  renderAdminPager($("auditPager"), state.audit, data?.logsCount || 0, "audit");
}

function articleStatusActions(article) {
  const slug = escapeHtml(article.slug);
  const status = article.contentStatus || "visible";
  if (status === "hidden") {
    return `<button class="ghost" data-article-status="${slug}" data-next-status="visible" type="button">恢复</button>`;
  }
  if (status === "pending") {
    return `
      <button class="ghost" data-article-status="${slug}" data-next-status="visible" type="button">放行</button>
      <button class="ghost danger-action" data-article-status="${slug}" data-next-status="hidden" type="button">隐藏</button>
    `;
  }
  return `<button class="ghost danger-action" data-article-status="${slug}" data-next-status="hidden" type="button">隐藏</button>`;
}

function commentStatusActions(comment) {
  const status = comment.contentStatus || "visible";
  if (status === "hidden") {
    return `<button class="ghost" data-comment-status="${comment.id}" data-next-status="visible" type="button">恢复</button>`;
  }
  if (status === "pending") {
    return `
      <button class="ghost" data-comment-status="${comment.id}" data-next-status="visible" type="button">放行</button>
      <button class="ghost danger-action" data-comment-status="${comment.id}" data-next-status="hidden" type="button">隐藏</button>
    `;
  }
  return `<button class="ghost danger-action" data-comment-status="${comment.id}" data-next-status="hidden" type="button">隐藏</button>`;
}

function renderAdminPager(target, pageState, total, scope) {
  const page = Math.floor(pageState.offset / pageState.limit) + 1;
  const totalPages = Math.max(1, Math.ceil(Number(total || 0) / pageState.limit));
  target.innerHTML = `
    <button class="ghost" data-page-scope="${scope}" data-page-direction="prev" type="button" ${
      page > 1 ? "" : "disabled"
    }>上一页</button>
    <span>${Number(total || 0)} 条 · 第 ${page}/${totalPages} 页</span>
    <button class="ghost" data-page-scope="${scope}" data-page-direction="next" type="button" ${
      page < totalPages ? "" : "disabled"
    }>下一页</button>
  `;
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
    return "待审核";
  }
  if (status === "rejected") {
    return "未通过";
  }
  return "已通过";
}

function reportStatusLabel(status) {
  if (status === "pending") {
    return "待处理";
  }
  if (status === "ignored") {
    return "已驳回";
  }
  return "已采纳";
}

function actionLabel(action) {
  const labels = {
    ai_pending_review: "AI 标记待审核",
    moderation_approve: "审核放行",
    moderation_reject: "审核驳回",
    manual_status_update: "手动更新状态",
    manual_hide: "手动隐藏",
    report_resolve: "举报已处理",
    report_ignore: "举报已驳回",
    report_hide: "举报已采纳并隐藏",
  };
  return labels[action] || action;
}

async function loadOverview() {
  const data = await request("/admin/overview");
  renderOverview(data);
  state.loadedViews.overviewView = true;
  return data;
}

async function loadModeration() {
  const [comments, articles] = await Promise.all([
    loadCommentModeration(),
    loadArticleModeration(),
  ]);
  const data = { comments, articles };
  renderModeration(data);
  state.loadedViews.moderationView = true;
  return data;
}

async function loadCommentModeration() {
  const filters = state.moderation.comments;
  filters.status = $("commentModerationStatus").value;
  filters.q = $("commentModerationQuery").value.trim();
  const params = new URLSearchParams({
    status: filters.status,
    limit: String(filters.limit),
    offset: String(filters.offset),
  });
  if (filters.q) {
    params.set("q", filters.q);
  }
  return request(`/admin/moderation/comments?${params.toString()}`);
}

async function loadArticleModeration() {
  const filters = state.moderation.articles;
  filters.status = $("articleModerationStatus").value;
  filters.q = $("articleModerationQuery").value.trim();
  const params = new URLSearchParams({
    status: filters.status,
    limit: String(filters.limit),
    offset: String(filters.offset),
  });
  if (filters.q) {
    params.set("q", filters.q);
  }
  return request(`/admin/moderation/articles?${params.toString()}`);
}

async function reviewModeration(kind, id, action) {
  const result = await requestNote(
    action === "approve" ? "审核放行备注" : "审核驳回备注",
    {
      confirmLabel: action === "approve" ? "确认放行" : "确认驳回",
      description:
        action === "approve"
          ? "确认后会将该内容恢复为可显示状态。"
          : "确认后会将该内容标记为未通过并设为不显示。",
      tone: action === "approve" ? "default" : "danger",
    },
  );
  if (!result?.confirmed) {
    return null;
  }
  const note = result.note;
  const path =
    kind === "article"
      ? `/admin/moderation/articles/${encodeURIComponent(id)}/review`
      : `/admin/moderation/comments/${encodeURIComponent(id)}/review`;
  const data = await request(path, {
    method: "POST",
    body: JSON.stringify({ action, note }),
  });
  return data;
}

async function reviewModerationBatch(kind, action, ids) {
  const result = await requestNote(
    action === "approve" ? "批量放行备注" : "批量驳回备注",
    {
      confirmLabel: action === "approve" ? "确认批量放行" : "确认批量驳回",
      description:
        action === "approve"
          ? "确认后会批量放行已选内容。"
          : "确认后会批量驳回已选内容。",
      tone: action === "approve" ? "default" : "danger",
    },
  );
  if (!result?.confirmed) {
    return null;
  }
  const note = result.note;
  for (const id of ids) {
    const path =
      kind === "article"
        ? `/admin/moderation/articles/${encodeURIComponent(id)}/review`
        : `/admin/moderation/comments/${encodeURIComponent(id)}/review`;
    await request(path, {
      method: "POST",
      body: JSON.stringify({ action, note }),
    });
  }
  return true;
}

async function loadArticles(options = {}) {
  if (options.reset) {
    state.articles.offset = 0;
  }
  const keyword = $("adminArticleQuery").value.trim();
  state.articles.status = $("adminArticleStatus").value;
  const params = new URLSearchParams({
    status: state.articles.status,
    limit: String(state.articles.limit),
    offset: String(state.articles.offset),
  });
  if (keyword) {
    params.set("q", keyword);
  }
  const data = await request(`/admin/articles?${params.toString()}`);
  state.articleDetailCache = {};
  renderArticles(data);
  state.loadedViews.articlesView = true;
  return data;
}

async function loadComments(options = {}) {
  if (options.reset) {
    state.comments.offset = 0;
  }
  const keyword = $("adminCommentQuery").value.trim();
  state.comments.status = $("adminCommentStatus").value;
  const params = new URLSearchParams({
    status: state.comments.status,
    limit: String(state.comments.limit),
    offset: String(state.comments.offset),
  });
  if (keyword) {
    params.set("q", keyword);
  }
  const path =
    state.comments.mode === "threads"
      ? `/admin/comment-threads?${params.toString()}`
      : `/admin/comments?${params.toString()}`;
  const data = await request(path);
  renderComments(data);
  state.loadedViews.commentsView = true;
  return data;
}

async function loadReports(options = {}) {
  if (options.reset) {
    state.reports.offset = 0;
  }
  state.reports.status = $("reportStatus").value;
  state.reports.type = $("reportType").value;
  const keyword = $("reportQuery").value.trim();
  const params = new URLSearchParams({
    status: state.reports.status,
    type: state.reports.type,
    limit: String(state.reports.limit),
    offset: String(state.reports.offset),
  });
  if (keyword) {
    params.set("q", keyword);
  }
  const data = await request(`/admin/reports?${params.toString()}`);
  renderReports(data);
  state.loadedViews.reportsView = true;
  return data;
}

async function reviewReport(reportId, action) {
  const result = await requestNote(
    action === "hide" ? "接受举报并隐藏内容" : "驳回举报请求",
    {
      defaultValue: action === "hide" ? "已接受举报并隐藏内容。" : "已驳回该举报请求。",
      description:
        action === "hide"
          ? "只有点击确认后才会执行隐藏，隐藏后内容将不再公开显示。"
          : "只有点击确认后才会驳回本次举报，内容状态不会改变。",
      confirmLabel: action === "hide" ? "确认隐藏" : "确认驳回",
      placeholder: action === "hide" ? "输入隐藏原因或处理依据" : "输入驳回原因或说明",
      tone: action === "hide" ? "danger" : "default",
    },
  );
  if (!result?.confirmed) {
    return null;
  }
  const note = result.note;
  await request(`/admin/reports/${encodeURIComponent(reportId)}/review`, {
    method: "POST",
    body: JSON.stringify({ action, note }),
  });
  return loadReports();
}

async function reviewReportBatch(action, ids) {
  const result = await requestNote(
    action === "hide" ? "批量接受举报并隐藏" : "批量驳回举报请求",
    {
      confirmLabel: action === "hide" ? "确认批量隐藏" : "确认批量驳回",
      description:
        action === "hide"
          ? "确认后会对已选举报执行隐藏处理。"
          : "确认后会批量驳回已选举报请求。",
      tone: action === "hide" ? "danger" : "default",
    },
  );
  if (!result?.confirmed) {
    return null;
  }
  const note = result.note;
  for (const id of ids) {
    await request(`/admin/reports/${encodeURIComponent(id)}/review`, {
      method: "POST",
      body: JSON.stringify({ action, note }),
    });
  }
  return loadReports();
}

async function loadAudit(options = {}) {
  if (options.reset) {
    state.audit.offset = 0;
  }
  state.audit.type = $("auditType").value;
  const keyword = $("auditQuery").value.trim();
  const params = new URLSearchParams({
    type: state.audit.type,
    limit: String(state.audit.limit),
    offset: String(state.audit.offset),
  });
  if (keyword) {
    params.set("q", keyword);
  }
  const data = await request(`/admin/audit-logs?${params.toString()}`);
  renderAudit(data);
  state.loadedViews.auditView = true;
  return data;
}

async function exportAuditLogs() {
  state.audit.type = $("auditType").value;
  const keyword = $("auditQuery").value.trim();
  const params = new URLSearchParams({
    type: state.audit.type,
  });
  if (keyword) {
    params.set("q", keyword);
  }
  const response = await fetch(`${API_BASE}/admin/audit-logs/export?${params.toString()}`, {
    headers: headers(),
  });
  if (!response.ok) {
    throw new Error("导出审计记录失败。");
  }
  const text = await response.text();
  const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "audit-logs.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function loadViewData(viewId = state.activeView, options = {}) {
  if (!state.token) {
    return null;
  }
  if (!options.force && state.loadedViews[viewId]) {
    return null;
  }
  if (viewId === "overviewView") {
    return loadOverview();
  }
  if (viewId === "moderationView") {
    return loadModeration();
  }
  if (viewId === "articlesView") {
    return loadArticles();
  }
  if (viewId === "commentsView") {
    return loadComments();
  }
  if (viewId === "reportsView") {
    return loadReports();
  }
  if (viewId === "auditView") {
    return loadAudit();
  }
  return null;
}

function pageStateForScope(scope) {
  if (scope === "article-moderation") {
    return state.moderation.articles;
  }
  if (scope === "comment-moderation") {
    return state.moderation.comments;
  }
  if (scope === "comments") {
    return state.comments;
  }
  if (scope === "reports") {
    return state.reports;
  }
  if (scope === "audit") {
    return state.audit;
  }
  return state.articles;
}

async function loadScope(scope) {
  if (scope === "article-moderation" || scope === "comment-moderation") {
    return loadViewData("moderationView", { force: true });
  }
  if (scope === "comments") {
    return loadComments();
  }
  if (scope === "reports") {
    return loadReports();
  }
  if (scope === "audit") {
    return loadAudit();
  }
  return loadArticles();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function excerpt(value, length = 140) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= length) {
    return text;
  }
  return `${text.slice(0, length - 1)}...`;
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

document.querySelectorAll("[data-admin-view]").forEach((item) => {
  item.addEventListener("click", (event) => {
    event.preventDefault();
    switchView(item.dataset.adminView);
  });
});

document.querySelectorAll("[data-admin-auth-mode]").forEach((tab) => {
  tab.addEventListener("click", () => setAuthMode(tab.dataset.adminAuthMode));
});

$("noteModalConfirmBtn").addEventListener("click", () => {
  closeNoteModal({
    confirmed: true,
    note: $("noteModalInput").value.trim(),
  });
});

$("noteModalCancelBtn").addEventListener("click", (event) => {
  event.preventDefault();
  event.stopPropagation();
  closeNoteModal({ confirmed: false, note: "" });
});

$("noteModalCancelIconBtn").addEventListener("click", (event) => {
  event.preventDefault();
  event.stopPropagation();
  closeNoteModal({ confirmed: false, note: "" });
});

$("noteModal").addEventListener("click", (event) => {
  if (event.target === $("noteModal")) {
    closeNoteModal({ confirmed: false, note: "" });
  }
});

$("noteModal").querySelector(".modal-panel").addEventListener("click", (event) => {
  event.stopPropagation();
});

$("articleModalCloseBtn").addEventListener("click", closeArticleModal);

$("articleModal").addEventListener("click", (event) => {
  if (event.target === $("articleModal")) {
    closeArticleModal();
  }
});

$("articleModal").querySelector(".modal-panel").addEventListener("click", (event) => {
  event.stopPropagation();
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }
  if (!$("noteModal").classList.contains("hidden")) {
    closeNoteModal({ confirmed: false, note: "" });
    return;
  }
  if (!$("articleModal").classList.contains("hidden")) {
    closeArticleModal();
  }
});

$("adminAuthSubmitBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    const path = state.authMode === "register" ? "/users" : "/users/login";
    const user = {
      email: $("adminEmail").value.trim(),
      password: $("adminPassword").value,
    };
    if (state.authMode === "register") {
      user.username = $("adminUsername").value.trim();
    }
    const data = await request(path, {
      method: "POST",
      body: JSON.stringify({ user }),
    });
    setToken(data.user.token, data.user);
    toast(`${state.authMode === "register" ? "注册" : "登录"}成功`);
    await loadViewData(state.activeView, { force: true });
  }).catch((error) => toast(error.message, "error"));
});

$("adminLogoutBtn").addEventListener("click", () => {
  setToken("", null);
  state.loadedViews = {};
  switchView("overviewView", { load: false });
  toast("已退出");
});

$("loadOverviewBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, () =>
    loadViewData("overviewView", { force: true }),
  ).catch((error) => toast(error.message, "error"));
});

$("loadModerationBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, () =>
    loadViewData("moderationView", { force: true }),
  ).catch((error) => toast(error.message, "error"));
});

$("searchCommentModerationBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    state.moderation.comments.offset = 0;
    await loadViewData("moderationView", { force: true });
  }).catch((error) => toast(error.message, "error"));
});

$("searchArticleModerationBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, async () => {
    state.moderation.articles.offset = 0;
    await loadViewData("moderationView", { force: true });
  }).catch((error) => toast(error.message, "error"));
});

$("commentModerationStatus").addEventListener("change", () => {
  state.moderation.comments.offset = 0;
  loadViewData("moderationView", { force: true }).catch((error) =>
    toast(error.message, "error"),
  );
});

$("articleModerationStatus").addEventListener("change", () => {
  state.moderation.articles.offset = 0;
  loadViewData("moderationView", { force: true }).catch((error) =>
    toast(error.message, "error"),
  );
});

$("commentModerationQuery").addEventListener("keydown", async (event) => {
  if (event.key === "Enter") {
    state.moderation.comments.offset = 0;
    await loadViewData("moderationView", { force: true }).catch((error) =>
      toast(error.message, "error"),
    );
  }
});

$("articleModerationQuery").addEventListener("keydown", async (event) => {
  if (event.key === "Enter") {
    state.moderation.articles.offset = 0;
    await loadViewData("moderationView", { force: true }).catch((error) =>
      toast(error.message, "error"),
    );
  }
});

$("loadAdminArticlesBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, () =>
    loadArticles({ reset: true }),
  ).catch((error) => toast(error.message, "error"));
});

$("adminArticleStatus").addEventListener("change", () => {
  loadArticles({ reset: true }).catch((error) => toast(error.message, "error"));
});

$("adminArticleQuery").addEventListener("keydown", async (event) => {
  if (event.key === "Enter") {
    await loadArticles({ reset: true }).catch((error) =>
      toast(error.message, "error"),
    );
  }
});

$("loadAdminCommentsBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, () =>
    loadComments({ reset: true }),
  ).catch((error) => toast(error.message, "error"));
});

$("adminCommentStatus").addEventListener("change", () => {
  loadComments({ reset: true }).catch((error) => toast(error.message, "error"));
});

document.querySelectorAll("[data-admin-comment-mode]").forEach((tab) => {
  tab.addEventListener("click", () => {
    state.comments.mode = tab.dataset.adminCommentMode;
    document.querySelectorAll("[data-admin-comment-mode]").forEach((item) => {
      item.classList.toggle("active", item.dataset.adminCommentMode === state.comments.mode);
      item.setAttribute(
        "aria-pressed",
        item.dataset.adminCommentMode === state.comments.mode ? "true" : "false",
      );
    });
    loadComments({ reset: true }).catch((error) => toast(error.message, "error"));
  });
});

$("adminCommentQuery").addEventListener("keydown", async (event) => {
  if (event.key === "Enter") {
    await loadComments({ reset: true }).catch((error) =>
      toast(error.message, "error"),
    );
  }
});

$("loadReportsBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, () => loadReports({ reset: true })).catch(
    (error) => toast(error.message, "error"),
  );
});

$("reportStatus").addEventListener("change", () => {
  loadReports({ reset: true }).catch((error) => toast(error.message, "error"));
});

$("reportType").addEventListener("change", () => {
  loadReports({ reset: true }).catch((error) => toast(error.message, "error"));
});

$("reportQuery").addEventListener("keydown", async (event) => {
  if (event.key === "Enter") {
    await loadReports({ reset: true }).catch((error) => toast(error.message, "error"));
  }
});

$("loadAuditBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, () => loadAudit({ reset: true })).catch(
    (error) => toast(error.message, "error"),
  );
});

$("exportAuditBtn").addEventListener("click", async (event) => {
  await withBusy(event.currentTarget, exportAuditLogs).catch((error) =>
    toast(error.message, "error"),
  );
});

$("auditType").addEventListener("change", () => {
  loadAudit({ reset: true }).catch((error) => toast(error.message, "error"));
});

$("auditQuery").addEventListener("keydown", async (event) => {
  if (event.key === "Enter") {
    await loadAudit({ reset: true }).catch((error) => toast(error.message, "error"));
  }
});

$("moderationView").addEventListener("click", async (event) => {
  const detailButton = event.target.closest("[data-article-detail]");
  if (detailButton) {
    await withBusy(detailButton, () => openArticleModal(detailButton.dataset.articleDetail)).catch(
      (error) => toast(error.message, "error"),
    );
    return;
  }
  const checkbox = event.target.closest("[data-select-scope]");
  if (checkbox) {
    toggleSelection(
      checkbox.dataset.selectScope,
      checkbox.dataset.selectId,
      checkbox.checked,
    );
    return;
  }
  const button = event.target.closest("[data-review-action]");
  if (!button) {
    return;
  }
  await withBusy(button, async () => {
    const result = await reviewModeration(
      button.dataset.reviewKind,
      button.dataset.id,
      button.dataset.reviewAction,
    );
    if (!result) {
      return;
    }
    await loadViewData("moderationView", { force: true });
    await loadOverview();
    toast("复核结果已保存");
  }).catch((error) => toast(error.message, "error"));
});

$("approveSelectedCommentsBtn").addEventListener("click", async (event) => {
  const ids = [...state.selections.commentModeration];
  if (!ids.length) {
    toast("请先选择评论。", "error");
    return;
  }
  await withBusy(event.currentTarget, async () => {
    const done = await reviewModerationBatch("comment", "approve", ids);
    if (!done) {
      return;
    }
    clearSelection("commentModeration");
    await loadViewData("moderationView", { force: true });
    await loadOverview();
    toast("已批量放行评论");
  }).catch((error) => toast(error.message, "error"));
});

$("rejectSelectedCommentsBtn").addEventListener("click", async (event) => {
  const ids = [...state.selections.commentModeration];
  if (!ids.length) {
    toast("请先选择评论。", "error");
    return;
  }
  await withBusy(event.currentTarget, async () => {
    const done = await reviewModerationBatch("comment", "reject", ids);
    if (!done) {
      return;
    }
    clearSelection("commentModeration");
    await loadViewData("moderationView", { force: true });
    await loadOverview();
    toast("已批量驳回评论");
  }).catch((error) => toast(error.message, "error"));
});

$("approveSelectedArticlesBtn").addEventListener("click", async (event) => {
  const ids = [...state.selections.articleModeration];
  if (!ids.length) {
    toast("请先选择文章。", "error");
    return;
  }
  await withBusy(event.currentTarget, async () => {
    const done = await reviewModerationBatch("article", "approve", ids);
    if (!done) {
      return;
    }
    clearSelection("articleModeration");
    await loadViewData("moderationView", { force: true });
    await loadOverview();
    toast("已批量放行文章");
  }).catch((error) => toast(error.message, "error"));
});

$("rejectSelectedArticlesBtn").addEventListener("click", async (event) => {
  const ids = [...state.selections.articleModeration];
  if (!ids.length) {
    toast("请先选择文章。", "error");
    return;
  }
  await withBusy(event.currentTarget, async () => {
    const done = await reviewModerationBatch("article", "reject", ids);
    if (!done) {
      return;
    }
    clearSelection("articleModeration");
    await loadViewData("moderationView", { force: true });
    await loadOverview();
    toast("已批量驳回文章");
  }).catch((error) => toast(error.message, "error"));
});

$("adminArticlesList").addEventListener("click", async (event) => {
  const detailButton = event.target.closest("[data-article-detail]");
  if (detailButton) {
    await withBusy(detailButton, () => openArticleModal(detailButton.dataset.articleDetail)).catch(
      (error) => toast(error.message, "error"),
    );
    return;
  }
  const button = event.target.closest("[data-article-status]");
  if (!button) {
    const row = event.target.closest("[data-slug]");
    if (row) {
      openArticleModal(row.dataset.slug).catch((error) => toast(error.message, "error"));
    }
    return;
  }
  await withBusy(button, async () => {
    const result = await requestNote("文章状态处理备注", {
      confirmLabel: button.dataset.nextStatus === "hidden" ? "确认隐藏" : "确认恢复",
      description:
        button.dataset.nextStatus === "hidden"
          ? "确认后文章将不再公开显示。"
          : "确认后文章会重新恢复显示。",
      placeholder: "输入本次状态调整的原因",
      tone: button.dataset.nextStatus === "hidden" ? "danger" : "default",
    });
    if (!result?.confirmed) {
      return;
    }
    const note = result.note;
    await request(
      `/admin/articles/${encodeURIComponent(button.dataset.articleStatus)}/status`,
      {
        method: "PUT",
        body: JSON.stringify({
          status: button.dataset.nextStatus,
          note,
        }),
      },
    );
    delete state.articleDetailCache[button.dataset.articleStatus];
    await loadArticles();
    await loadOverview();
    toast("文章状态已更新");
  }).catch((error) => toast(error.message, "error"));
});

$("adminCommentsList").addEventListener("click", async (event) => {
  const threadButton = event.target.closest("[data-toggle-thread]");
  if (threadButton) {
    await withBusy(threadButton, () =>
      toggleCommentThread(threadButton.dataset.toggleThread),
    ).catch((error) => toast(error.message, "error"));
    return;
  }
  const detailButton = event.target.closest("[data-article-detail]");
  if (detailButton) {
    await withBusy(detailButton, () => openArticleModal(detailButton.dataset.articleDetail)).catch(
      (error) => toast(error.message, "error"),
    );
    return;
  }
  const button = event.target.closest("[data-comment-status]");
  if (!button) {
    const row = event.target.closest("[data-slug]");
    if (row && state.comments.mode === "threads") {
      await withBusy(row, () => openArticleModal(row.dataset.slug)).catch((error) =>
        toast(error.message, "error"),
      );
    }
    return;
  }
  await withBusy(button, async () => {
    const result = await requestNote("评论状态处理备注", {
      confirmLabel: button.dataset.nextStatus === "hidden" ? "确认隐藏" : "确认恢复",
      description:
        button.dataset.nextStatus === "hidden"
          ? "确认后评论将不再公开显示。"
          : "确认后评论会重新恢复显示。",
      placeholder: "输入本次状态调整的原因",
      tone: button.dataset.nextStatus === "hidden" ? "danger" : "default",
    });
    if (!result?.confirmed) {
      return;
    }
    const note = result.note;
    await request(
      `/admin/comments/${encodeURIComponent(button.dataset.commentStatus)}/status`,
      {
        method: "PUT",
        body: JSON.stringify({
          status: button.dataset.nextStatus,
          note,
        }),
      },
    );
    await loadComments();
    await loadOverview();
    toast("评论状态已更新");
  }).catch((error) => toast(error.message, "error"));
});

$("articleModalComments").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-comment-status]");
  if (!button) {
    return;
  }
  await withBusy(button, async () => {
    const result = await requestNote("评论状态处理备注", {
      confirmLabel: button.dataset.nextStatus === "hidden" ? "确认隐藏" : "确认恢复",
      description:
        button.dataset.nextStatus === "hidden"
          ? "确认后评论将不再公开显示。"
          : "确认后评论会重新恢复显示。",
      placeholder: "输入本次状态调整的原因",
      tone: button.dataset.nextStatus === "hidden" ? "danger" : "default",
    });
    if (!result?.confirmed) {
      return;
    }
    await request(
      `/admin/comments/${encodeURIComponent(button.dataset.commentStatus)}/status`,
      {
        method: "PUT",
        body: JSON.stringify({
          status: button.dataset.nextStatus,
          note: result.note,
        }),
      },
    );
    await loadComments();
    if (state.articleModalSlug) {
      $("articleModalComments").innerHTML = renderArticleThreadComments(
        await loadArticleCommentsForAdmin(state.articleModalSlug),
      );
    }
    await loadOverview();
    toast("评论状态已更新");
  }).catch((error) => toast(error.message, "error"));
});

$("reportsList").addEventListener("click", async (event) => {
  const checkbox = event.target.closest("[data-select-scope]");
  if (checkbox) {
    toggleSelection(
      checkbox.dataset.selectScope,
      checkbox.dataset.selectId,
      checkbox.checked,
    );
    return;
  }
  const button = event.target.closest("[data-report-action]");
  if (!button) {
    return;
  }
  await withBusy(button, async () => {
    const result = await reviewReport(
      button.dataset.reportId,
      button.dataset.reportAction,
    );
    if (!result) {
      return;
    }
    await loadOverview();
    await loadAudit({ reset: true });
    toast("举报处理已保存");
  }).catch((error) => toast(error.message, "error"));
});

$("ignoreSelectedReportsBtn").addEventListener("click", async (event) => {
  const ids = [...state.selections.reports];
  if (!ids.length) {
    toast("请先选择举报。", "error");
    return;
  }
  await withBusy(event.currentTarget, async () => {
    const done = await reviewReportBatch("ignore", ids);
    if (!done) {
      return;
    }
    clearSelection("reports");
    await loadOverview();
    await loadAudit({ reset: true });
    toast("已批量驳回举报请求");
  }).catch((error) => toast(error.message, "error"));
});

$("hideSelectedReportsBtn").addEventListener("click", async (event) => {
  const ids = [...state.selections.reports];
  if (!ids.length) {
    toast("请先选择举报。", "error");
    return;
  }
  await withBusy(event.currentTarget, async () => {
    const done = await reviewReportBatch("hide", ids);
    if (!done) {
      return;
    }
    clearSelection("reports");
    await loadOverview();
    await loadAudit({ reset: true });
    toast("已批量接受举报并隐藏内容");
  }).catch((error) => toast(error.message, "error"));
});

document.querySelectorAll(".pager").forEach((pager) => {
  pager.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-page-scope]");
    if (!button) {
      return;
    }
    const scope = button.dataset.pageScope;
    const delta = button.dataset.pageDirection === "next" ? 1 : -1;
    const pageState = pageStateForScope(scope);
    pageState.offset = Math.max(0, pageState.offset + delta * pageState.limit);
    await loadScope(scope).catch((error) => toast(error.message, "error"));
  });
});

setAuthMode("login");
renderAccount();
switchView("overviewView", { load: false });
if (state.token) {
  loadViewData("overviewView").catch((error) => toast(error.message, "error"));
}
