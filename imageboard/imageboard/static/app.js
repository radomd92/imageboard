const THEMES = ["rorisu", "macos", "win98", "classic"];
const state = {
  view: "home",
  page: 1,
  query: "",
  tag: "",
  theme: "rorisu",
  me: null,
  history: ["home"],
  historyIndex: 0,
  readOnly: location.hostname.endsWith(".onion"),
  indexedFolders: new Set(),
  indexJobs: new Set(),
};
const el = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const api = async (url, options = {}) => {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = response.statusText;
    try {
      message = (await response.json()).detail || message;
    } catch {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
};
const notice = (message, error = false) => {
  const box = el("notice");
  box.textContent = message;
  box.className = `show${error ? " error" : ""}`;
  setTimeout(() => (box.className = ""), 4500);
};
const size = (bytes) =>
  bytes == null
    ? "Unknown"
    : bytes < 1024 * 1024
      ? `${Math.round(bytes / 1024)} KB`
      : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
const mediaCard = (item) =>
  `<article class="media-card"><button class="favorite-toggle" data-favorite="${item.id}" data-active="${item.favorite}" title="${item.favorite ? "Remove favorite" : "Add favorite"}">${item.favorite ? "★" : "☆"}</button><button data-image="${item.id}"><div class="media-preview">${item.kind === "video" ? '<div class="video-placeholder">VIDEO</div>' : `<img loading="lazy" src="${item.thumbnail_url}" alt="">`}<span class="media-type">${item.kind.toUpperCase()}</span></div><div class="card-info"><strong>${esc(item.name)}</strong><small>${size(item.file_size)} · ${item.hits} views</small><div class="tag-line">${item.tags.map(esc).join(" · ") || "untagged"}</div></div></button></article>`;
const cards = (items) =>
  `<div class="media-grid">${items.length ? items.map(mediaCard).join("") : '<div class="empty">Nothing found in this view.</div>'}</div>`;
const header = (title, subtitle, action = "") =>
  `<div class="view-header"><div><h2>${esc(title)}</h2><p>${esc(subtitle)}</p></div>${action}</div>`;

function applyTheme(theme) {
  if (!THEMES.includes(theme)) return;
  state.theme = theme;
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("paradise.theme", theme);
  } catch (error) {}
  document
    .querySelectorAll(".theme-options button")
    .forEach((button) =>
      button.classList.toggle("active", button.dataset.themeChoice === theme),
    );
}
applyTheme(document.documentElement.dataset.theme || "rorisu");

async function loadImages(params = {}) {
  const query = new URLSearchParams({
    page: params.page || 1,
    limit: params.limit || 30,
  });
  if (params.q) query.set("q", params.q);
  if (params.tag) query.set("tag", params.tag);
  if (params.untagged) query.set("untagged", "true");
  if (params.favorite) query.set("favorite", "true");
  return api(`/api/images?${query}`);
}

async function renderHome() {
  const [dashboard, recent] = await Promise.all([
    api("/api/dashboard"),
    loadImages({ limit: 8 }),
  ]);
  el("path").textContent = "Paradise HD : Dashboard";
  el("view").innerHTML =
    `${header("Welcome to Paradise", "Private media catalog and context archive")}<div class="stats"><div class="stat"><strong>${dashboard.total}</strong><span>INDEXED MEDIA</span></div><div class="stat"><strong>${dashboard.untagged}</strong><span>NEEDS TAGS</span></div><div class="stat"><strong>${dashboard.popular_tags.length}</strong><span>ACTIVE TAGS / 30 DAYS</span></div></div><div class="section-title"><h3>RECENTLY INDEXED</h3><button class="button" data-go="library">View All</button></div>${cards(recent.items)}<div class="section-title"><h3>POPULAR TAGS</h3></div><div class="tag-grid">${dashboard.popular_tags.length ? dashboard.popular_tags.map((t) => `<button class="tag-card" data-tag="${esc(t.name)}"><strong>${esc(t.name)}</strong><span>${t.hits} hits</span></button>`).join("") : "<p>No view history yet.</p>"}</div>`;
  el("status").textContent =
    `${dashboard.total} items, ${dashboard.untagged} awaiting context`;
}

async function renderLibrary(untagged = false, favorite = false) {
  const data = await loadImages({
    page: state.page,
    q: state.query,
    tag: state.tag,
    untagged,
    favorite,
  });
  const title = state.tag
    ? `Tag: ${state.tag}`
    : favorite
      ? "Favorites"
      : untagged
        ? "Needs Tags"
        : "Media Library";
  el("path").textContent = `Paradise HD : ${title}`;
  el("view").innerHTML =
    `${header(title, `${data.total} indexed items`)}${cards(data.items)}<div class="pager"><button class="button" data-page="${state.page - 1}" ${state.page === 1 ? "disabled" : ""}>Previous</button><span>Page ${state.page} of ${Math.max(1, Math.ceil(data.total / data.limit))}</span><button class="button" data-page="${state.page + 1}" ${state.page * data.limit >= data.total ? "disabled" : ""}>Next</button></div>`;
  el("status").textContent =
    `Showing ${data.items.length} of ${data.total} items`;
}

async function renderTags() {
  const tags = await api("/api/tags");
  el("path").textContent = "Paradise HD : Tags";
  el("view").innerHTML =
    `${header("Tag Directory", "Browse catalog by assigned context")}<div class="tag-grid">${tags.length ? tags.map((t) => `<button class="tag-card" data-tag="${esc(t.name)}"><strong>${esc(t.name)}</strong><span>${t.count} files</span></button>`).join("") : '<div class="empty">No tags yet.</div>'}</div>`;
  el("status").textContent = `${tags.length} tags`;
}

const crumbs = (path) => {
  const parts = path ? path.split("$") : [];
  return `<button data-folder="">Paradise HD</button>${parts.map((part, i) => `›<button data-folder="${esc(parts.slice(0, i + 1).join("$"))}">${esc(part)}</button>`).join("")}`;
};
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function watchIndexJob(id) {
  while (true) {
    await delay(1500);
    const job = await api(`/api/index-jobs/${id}`);
    if (job.status === "pending" || job.status === "running") {
      el("status").textContent = `Indexing: ${job.processed} files processed`;
      continue;
    }
    if (job.status === "succeeded")
      notice(
        `Index complete: ${job.indexed} added, ${job.updated} updated, ${job.deindexed} removed.`,
      );
    else if (job.status === "failed") notice("Index job failed.", true);
    else notice("Index job cancelled.", true);
    state.indexJobs.delete(id);
    return;
  }
}
async function queueFolderIndex(path) {
  if (state.readOnly || state.indexedFolders.has(path)) return;
  state.indexedFolders.add(path);
  try {
    const job = await api("/api/index-jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ path }),
    });
    if (!state.indexJobs.has(job.id)) {
      state.indexJobs.add(job.id);
      notice("Index job queued.");
      watchIndexJob(job.id).catch((error) => {
        state.indexJobs.delete(job.id);
        notice(error.message, true);
      });
    }
  } catch (error) {
    state.indexedFolders.delete(path);
    notice(error.message, true);
  }
}
async function renderExplorer(path = "") {
  const data = await api(`/api/explore?path=${encodeURIComponent(path)}`);
  state.folder = data.path;
  el("path").textContent =
    `Paradise HD : ${data.path.replaceAll("$", " : ") || "Media"}`;
  const entries = data.entries
    .map(
      (item) =>
        `<article class="file" data-${item.type === "directory" ? "folder" : item.type === "document" ? "document" : "preview"}="${esc(item.path)}"><div class="file-preview">${item.type === "directory" ? '<div class="folder-icon"></div>' : item.type === "document" ? '<div class="document-placeholder">TEXT</div>' : item.type === "video" ? '<div class="video-placeholder">VIDEO</div>' : `<img loading="lazy" src="${item.thumbnail_url}" alt="">`}</div><strong class="file-name">${esc(item.name)}</strong>${item.type !== "directory" && item.indexed ? '<span class="indexed">✓ Indexed</span>' : ""}</article>`,
    )
    .join("");
  el("view").innerHTML =
    `${header("Media Explorer", "Browse mounted filesystem; indexing runs in the background.")}<section class="finder"><div class="breadcrumbs">${crumbs(data.path)}</div><div class="file-grid">${entries || '<div class="empty">Folder is empty.</div>'}</div></section>`;
  el("status").textContent =
    `${data.entries.length} entries in /${data.path.replaceAll("$", "/")}`;
  queueFolderIndex(data.path);
}

async function readDocument(path) {
  const documentData = await api(
    `/api/documents/read?path=${encodeURIComponent(path)}`,
  );
  el("document-reader-title").textContent = documentData.path.replaceAll(
    "$",
    "/",
  );
  const content = documentData.truncated
    ? `${documentData.content}\n\n[Document truncated at 1 MiB]`
    : documentData.content;
  // textContent renders HTML source as text and never executes embedded scripts.
  el("document-reader-content").textContent = content;
  el("document-reader").showModal();
}

function commentTree(comments) {
  const map = new Map(comments.map((c) => [c.id, { ...c, children: [] }])),
    roots = [];
  for (const item of map.values())
    (item.reply_to && map.has(item.reply_to)
      ? map.get(item.reply_to).children
      : roots
    ).push(item);
  const draw = (items, d = 0) =>
    items
      .map(
        (c) =>
          `<div class="comment depth-${Math.min(d, 2)}"><strong>${esc(c.author || "Deleted user")}</strong> <small>${new Date(c.created_at).toLocaleString()}</small><p>${esc(c.text)}</p>${state.readOnly ? "" : `<button class="button" data-reply="${c.id}">Reply</button>`}${draw(c.children, d + 1)}</div>`,
      )
      .join("");
  return draw(roots);
}
async function inspect(id) {
  const item = await api(`/api/images/${id}`);
  el("inspector-title").textContent = item.name;
  const edit =
    state.me.admin && !state.readOnly
      ? `<form id="metadata-form" class="edit-form"><strong>EDIT METADATA</strong><label>Title<input name="name" maxlength="200" value="${esc(item.name)}"></label><label>Tags<input name="tags" maxlength="1000" value="${esc(item.tags.join(", "))}"></label><button class="button">Save Changes</button></form>`
      : "";
  const source = state.readOnly ? item.media_url : item.file_url;
  const commentForm = state.readOnly
    ? ""
    : `<form id="comment-form" class="edit-form"><input type="hidden" name="reply_to"><label id="reply-label">Add context<textarea name="text" maxlength="500" required></textarea></label><button class="button">Post Comment</button></form>`;
  const favorite = state.readOnly
    ? ""
    : `<button class="button favorite-action" data-favorite="${item.id}" data-active="${item.favorite}">${item.favorite ? "★ Remove Favorite" : "☆ Add Favorite"}</button>`;
  el("inspector-body").innerHTML =
    `<div class="inspector-grid"><div>${item.kind === "video" ? `<video class="hero-media" controls preload="none" src="${source}"></video>` : `<img class="hero-media" src="${source}" alt="${esc(item.name)}">`}</div><aside><div class="info-table"><div class="info-row"><span>Kind</span><span>${item.kind}</span></div><div class="info-row"><span>Size</span><span>${size(item.file_size)}</span></div><div class="info-row"><span>Views</span><span>${item.hits}</span></div><div class="info-row"><span>Uploader</span><span>${esc(item.uploader || "Unknown")}</span></div><div class="info-row"><span>Indexed</span><span>${new Date(item.created_at).toLocaleString()}</span></div><div class="info-row"><span>Path</span><span>${esc(item.path.replaceAll("$", "/"))}</span></div></div><div class="tag-line">${item.tags.map(esc).join(" · ") || "untagged"}</div>${favorite}${edit}</aside></div><section class="comments"><div class="section-title"><h3>COMMENTS</h3></div><div id="comment-list">${commentTree(item.comments) || "<p>No comments yet.</p>"}</div>${commentForm}</section>`;
  el("inspector").showModal();
  const metadata = el("metadata-form");
  if (metadata)
    metadata.onsubmit = async (event) => {
      event.preventDefault();
      const form = new FormData(event.target);
      try {
        await api(`/api/images/${id}`, {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ name: form.get("name") }),
        });
        await api(`/api/images/${id}/context`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            tags: form
              .get("tags")
              .split(",")
              .map((t) => t.trim())
              .filter(Boolean),
          }),
        });
        notice("Metadata saved.");
        el("inspector").close();
        render();
      } catch (error) {
        notice(error.message, true);
      }
    };
  const comments = el("comment-form");
  if (comments) {
    el("comment-list").onclick = (event) => {
      if (event.target.dataset.reply) {
        comments.reply_to.value = event.target.dataset.reply;
        el("reply-label").firstChild.textContent =
          `Reply to comment #${event.target.dataset.reply}`;
      }
    };
    comments.onsubmit = async (event) => {
      event.preventDefault();
      const form = new FormData(event.target);
      try {
        await api(`/api/images/${id}/comments`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            text: form.get("text"),
            reply_to: form.get("reply_to")
              ? Number(form.get("reply_to"))
              : null,
          }),
        });
        inspect(id);
      } catch (error) {
        notice(error.message, true);
      }
    };
  }
}

async function render() {
  try {
    if (state.view === "home") await renderHome();
    else if (state.view === "tags") await renderTags();
    else if (state.view === "explorer")
      await renderExplorer(state.folder || "");
    else
      await renderLibrary(
        state.view === "untagged",
        state.view === "favorites",
      );
  } catch (error) {
    el("view").innerHTML =
      `<div class="empty"><strong>Could not open this view.</strong><p>${esc(error.message)}</p></div>`;
    notice(error.message, true);
  }
  document
    .querySelectorAll("nav button")
    .forEach((b) =>
      b.classList.toggle("active", b.dataset.view === state.view),
    );
}
function navigate(view, push = true) {
  state.view = view;
  state.page = 1;
  state.tag = "";
  state.query = "";
  el("search").value = "";
  if (push) {
    state.history = state.history.slice(0, state.historyIndex + 1);
    state.history.push(view);
    state.historyIndex++;
  }
  render();
}
document.addEventListener("click", async (event) => {
  const target = event.target.closest(
    "button,[data-image],[data-folder],[data-preview],[data-document]",
  );
  if (!target) return;
  if (target.dataset.view) navigate(target.dataset.view);
  if (target.dataset.themeChoice) applyTheme(target.dataset.themeChoice);
  if (target.dataset.go) navigate(target.dataset.go);
  if (target.dataset.image) inspect(target.dataset.image);
  if (target.dataset.favorite) {
    const active = target.dataset.active === "true";
    try {
      await api(`/api/images/${target.dataset.favorite}/favorite`, {
        method: active ? "DELETE" : "PUT",
      });
      if (target.classList.contains("favorite-action")) {
        el("inspector").close();
        await inspect(target.dataset.favorite);
      } else render();
    } catch (error) {
      notice(error.message, true);
    }
  }
  if (target.dataset.tag) {
    state.view = "library";
    state.tag = target.dataset.tag;
    state.page = 1;
    render();
  }
  if (target.dataset.page) {
    state.page = Number(target.dataset.page);
    render();
  }
  if (target.dataset.folder !== undefined)
    renderExplorer(target.dataset.folder);
  if (target.dataset.preview) {
    const indexed = await loadImages({ q: target.dataset.preview, limit: 1 });
    if (indexed.items.length) inspect(indexed.items[0].id);
    else notice("File is being indexed in the background.");
  }
  if (target.dataset.document) {
    try {
      await readDocument(target.dataset.document);
    } catch (error) {
      notice(error.message, true);
    }
  }
  if (target.dataset.close) el(target.dataset.close).close();
});
el("search").addEventListener("search", () => {
  state.query = el("search").value.trim();
  state.view = "library";
  state.page = 1;
  render();
});
el("search").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    state.query = event.target.value.trim();
    state.view = "library";
    state.page = 1;
    render();
  }
});
el("back").onclick = () => {
  if (state.historyIndex > 0) {
    state.historyIndex--;
    navigate(state.history[state.historyIndex], false);
  }
};
el("forward").onclick = () => {
  if (state.historyIndex < state.history.length - 1) {
    state.historyIndex++;
    navigate(state.history[state.historyIndex], false);
  }
};
el("inspector").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});
el("document-reader").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});
const releaseInspectorMedia = () => {
  const body = el("inspector-body");
  body.querySelectorAll("video").forEach((video) => {
    video.pause();
    video.removeAttribute("src");
    video.load();
  });
  body.querySelectorAll("img").forEach((image) => image.removeAttribute("src"));
  body.replaceChildren();
};
el("inspector").addEventListener("close", releaseInspectorMedia);
addEventListener("pagehide", releaseInspectorMedia);
setInterval(
  () =>
    (el("clock").textContent = new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    })),
  1000,
);
(async () => {
  try {
    state.me = await api("/api/me");
    el("username").textContent = state.me.name;
    el("role").textContent = state.readOnly
      ? "READ ONLY"
      : state.me.admin
        ? "ADMINISTRATOR"
        : "MEMBER";
    document
      .querySelectorAll(".admin-only")
      .forEach((node) =>
        node.classList.toggle("hidden", !state.me.admin || state.readOnly),
      );
    await render();
  } catch (error) {
    notice(error.message, true);
  }
})();
