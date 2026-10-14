const THEMES = ["rorisu", "macos", "win98", "classic"];
const MAX_COMMENT_BYTES = 8 * 1024;
const state = {
  view: "home",
  page: 1,
  query: "",
  tag: "",
  theme: "rorisu",
  me: null,
  userID: null,
  userQuery: "",
  commentCursor: "",
  readOnly: location.hostname.endsWith(".onion"),
  indexedFolders: new Set(),
  indexJobs: new Set(),
};
const el = (id) => document.getElementById(id);
const sidebar = el("sidebar");
const drawerToggle = el("drawer-toggle");
const drawerBackdrop = el("drawer-backdrop");
const mobileViewport = matchMedia("(max-width: 760px)");
function setDrawer(open) {
  const isOpen = open && mobileViewport.matches;
  document.body.classList.toggle("drawer-open", isOpen);
  sidebar.inert = !isOpen && mobileViewport.matches;
  drawerToggle.setAttribute("aria-expanded", String(isOpen));
  drawerToggle.setAttribute(
    "aria-label",
    isOpen ? "Close navigation" : "Open navigation",
  );
  if (isOpen) requestAnimationFrame(() => sidebar.querySelector("nav button")?.focus());
}
setDrawer(false);
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
const tagLinks = (tags) =>
  tags.length
    ? tags.map((tag) => `<button class="tag-link" type="button" data-tag="${esc(tag)}">${esc(tag)}</button>`).join(" · ")
    : "untagged";
const mediaCard = (item) =>
  `<article class="media-card"><button class="favorite-toggle" data-favorite="${item.id}" data-active="${item.favorite}" title="${item.favorite ? "Remove favorite" : "Add favorite"}">${item.favorite ? "★" : "☆"}</button><div class="media-open" data-image="${item.id}" role="button" tabindex="0"><div class="media-preview">${item.kind === "video" ? `<div class="video-placeholder">VIDEO</div><img class="video-thumbnail" loading="lazy" src="${item.thumbnail_url}" alt="">` : `<img loading="lazy" src="${item.thumbnail_url}" alt="">`}<span class="media-type">${item.kind.toUpperCase()}</span></div><div class="card-info"><strong>${esc(item.name)}</strong><small>${size(item.file_size)} · ${item.hits} views</small><div class="tag-line">${tagLinks(item.tags)}</div></div></div></article>`;
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

async function refreshMe() {
  state.me = await api("/api/me");
  el("username").textContent = state.me.name;
  el("username").href = `#/users/${state.me.id}`;
  el("role").textContent = `${state.me.admin ? "ADMINISTRATOR" : "MEMBER"}${state.readOnly ? " · MEDIA READ ONLY" : ""}`;
  document.querySelectorAll(".admin-only").forEach((node) => {
    node.classList.toggle("hidden", !state.me.admin || (state.readOnly && !node.classList.contains("account-admin")));
  });
}

const passwordFields = () => `<label>New password<input name="password" type="password" minlength="14" maxlength="256" autocomplete="new-password" required></label><label>Confirm password<input name="confirmation" type="password" minlength="14" maxlength="256" autocomplete="new-password" required></label><p>14–256 characters. Passwords are stored as salted scrypt hashes.</p>`;
const accountRequest = (url, method, body) => api(url, {
  method,
  headers: { "content-type": "application/json", "X-Imageboard-Request": "account" },
  body: JSON.stringify(body),
});

function bindAccountForm(form, submit) {
  form.onsubmit = async (event) => {
    event.preventDefault();
    const errorBox = form.querySelector(".form-error");
    errorBox.textContent = "";
    const data = new FormData(form);
    if (data.has("confirmation") && data.get("password") !== data.get("confirmation")) {
      errorBox.textContent = "Passwords do not match.";
      return;
    }
    const button = form.querySelector('[type="submit"]');
    button.disabled = true;
    try {
      await submit(data);
    } catch (error) {
      errorBox.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };
}

function showReauthentication(message) {
  if (el("password-reset").open) el("password-reset").close();
  el("view").innerHTML = `${header("Account updated", message)}<p>Sign in again through browser HTTP authentication. If browser keeps sending old credentials, close authenticated browser session and reopen site.</p><button id="reauthenticate" type="button" class="button">Sign In Again</button>`;
  el("reauthenticate").onclick = () => location.reload();
  notice(message);
}

async function renderUsers() {
  // API remains the authority even when frontend identity is stale.
  const routeHash = location.hash;
  const data = await api(`/api/admin/users?${new URLSearchParams({ page: state.page, q: state.userQuery })}`);
  if (state.view !== "users" || location.hash !== routeHash) return;
  el("path").textContent = "Paradise HD : Users";
  el("view").innerHTML = `${header("Users", `${data.total} accounts · administrator access`)}
    <form id="user-search" class="account-search"><label>Find username<input name="q" type="search" maxlength="100" value="${esc(state.userQuery)}"></label><button class="button" type="submit">Search</button></form>
    <div class="account-table-wrap"><table class="account-table"><thead><tr><th>Username</th><th>Permissions and status</th><th>Password</th></tr></thead><tbody>${data.items.map((item) => `<tr><td><a href="#/users/${item.id}">${esc(item.name)}</a><small>Joined ${new Date(item.registered).toLocaleDateString()}</small></td><td><form class="account-status" data-user-id="${item.id}"><label><input type="checkbox" name="admin" ${item.admin ? "checked" : ""}> Admin</label><label><input type="checkbox" name="disabled" ${item.disabled ? "checked" : ""}> Disabled</label><button class="button" type="submit">Save</button><p class="form-error" role="alert"></p></form></td><td><button type="button" class="button" data-reset-user="${item.id}">Reset Password</button></td></tr>`).join("") || '<tr><td colspan="3">No accounts found.</td></tr>'}</tbody></table></div>
    <div class="pager"><button class="button" type="button" id="users-previous" ${data.page <= 1 ? "disabled" : ""}>Previous</button><span>Page ${data.page} of ${Math.max(1, Math.ceil(data.total / data.limit))}</span><button class="button" type="button" id="users-next" ${data.page * data.limit >= data.total ? "disabled" : ""}>Next</button></div>
    <form id="create-user" class="edit-form account-form"><h3>Create User</h3><label>Username<input name="name" minlength="3" maxlength="100" autocomplete="off" required></label>${passwordFields()}<label class="checkbox-label"><input name="admin" type="checkbox"> Administrator</label><p class="form-error" role="alert"></p><button class="button" type="submit">Create User</button></form>`;
  el("status").textContent = `${data.total} accounts`;
  const usersRoute = (page, q = state.userQuery) => { location.hash = `#/users?${new URLSearchParams({ page, q })}`; };
  el("user-search").onsubmit = (event) => {
    event.preventDefault();
    usersRoute(1, new FormData(event.target).get("q"));
  };
  el("users-previous").onclick = () => usersRoute(data.page - 1);
  el("users-next").onclick = () => usersRoute(data.page + 1);
  const createForm = el("create-user");
  bindAccountForm(createForm, async (form) => {
    await accountRequest("/api/admin/users", "POST", { name: form.get("name"), password: form.get("password"), admin: form.has("admin") });
    createForm.reset();
    notice("User created.");
    if (state.view === "users") await renderUsers();
  });
  document.querySelectorAll(".account-status").forEach((form) => {
    const item = data.items.find((item) => item.id === Number(form.dataset.userId));
    bindAccountForm(form, async (fields) => {
      const disabled = fields.has("disabled");
      if (disabled && !item.disabled && !confirm(`Disable ${item.name}? Access stops immediately; comments remain.`)) return;
      await accountRequest(`/api/admin/users/${item.id}`, "PATCH", { admin: fields.has("admin"), disabled });
      if (item.id === state.me.id && disabled) {
        showReauthentication("Your account is now disabled. Sign in with another active account.");
        return;
      }
      await refreshMe();
      notice("Account updated.");
      if (!state.me.admin) location.hash = `#/users/${state.me.id}`;
      else if (state.view === "users") await renderUsers();
    });
  });
  document.querySelectorAll("[data-reset-user]").forEach((button) => {
    button.onclick = () => {
      const item = data.items.find((item) => item.id === Number(button.dataset.resetUser));
      const form = el("password-reset-form");
      form.reset();
      form.querySelector(".form-error").textContent = "";
      el("password-reset-user").textContent = `Set new password for ${item.name}.`;
      bindAccountForm(form, async (fields) => {
        await accountRequest(`/api/admin/users/${item.id}/password`, "PUT", { password: fields.get("password") });
        form.reset();
        el("password-reset").close();
        if (item.id === state.me.id) showReauthentication("Password changed. Old password no longer works.");
        else notice("Password reset.");
      });
      el("password-reset").showModal();
    };
  });
}

async function renderProfile() {
  const routeHash = location.hash;
  const profileID = state.userID;
  const cursor = state.commentCursor;
  const [profile, history] = await Promise.all([
    api(`/api/users/${profileID}`),
    api(`/api/users/${profileID}/comments?${new URLSearchParams({ cursor })}`),
  ]);
  if (state.view !== "profile" || location.hash !== routeHash) return;
  const base = `#/users/${profile.id}`;
  const comments = history.items.map((comment) => {
    const params = new URLSearchParams({ image: comment.image_id, comment: comment.id });
    if (cursor) params.set("cursor", cursor);
    return `<article class="comment"><small>${new Date(comment.created_at).toLocaleString()}${comment.reply_to ? " · Reply" : ""}</small><p>${esc(comment.text)}</p><a href="${base}?${params}">View thread: ${esc(comment.image_name)}</a></article>`;
  }).join("");
  el("path").textContent = `Paradise HD : User : ${profile.name}`;
  el("view").innerHTML = `${header(profile.name, `Joined ${new Date(profile.registered).toLocaleDateString()} · ${profile.comment_count} comments`)}
    ${profile.id === state.me.id ? `<form id="own-password" class="edit-form account-form"><h3>Change My Password</h3><label>Current password<input name="current_password" type="password" autocomplete="current-password" required></label>${passwordFields()}<p class="form-error" role="alert"></p><button class="button" type="submit">Change Password</button></form>` : ""}
    <div class="section-title"><h3>COMMENT HISTORY</h3></div>${comments || '<p>No comments yet.</p>'}
    <div class="pager">${cursor ? `<a class="button" href="${base}">Newest comments</a>` : ""}${history.next_cursor ? `<a class="button" href="${base}?cursor=${encodeURIComponent(history.next_cursor)}">Older comments</a>` : ""}</div>`;
  el("status").textContent = `${profile.comment_count} comments across media pages`;
  const ownForm = el("own-password");
  if (ownForm) bindAccountForm(ownForm, async (form) => {
    await accountRequest("/api/me/password", "PUT", { current_password: form.get("current_password"), password: form.get("password") });
    ownForm.reset();
    showReauthentication("Password changed. Old password no longer works.");
  });
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
          `<div id="comment-${c.id}" tabindex="-1" class="comment depth-${Math.min(d, 2)}"><strong>${c.author_id ? `<a href="#/users/${c.author_id}">${esc(c.author)}</a>` : esc(c.author || "Deleted user")}</strong> <small>${new Date(c.created_at).toLocaleString()}</small><p>${esc(c.text)}</p>${state.readOnly ? "" : `<button class="button" data-reply="${c.id}">Reply</button>`}${draw(c.children, d + 1)}</div>`,
      )
      .join("");
  return draw(roots);
}
async function inspect(id, commentID = null) {
  const item = await api(`/api/images/${id}`);
  el("inspector-title").textContent = item.name;
  const edit =
    state.me.admin && !state.readOnly
      ? `<form id="metadata-form" class="edit-form"><strong>EDIT METADATA</strong><label>Title<input name="name" maxlength="200" value="${esc(item.name)}"></label><label>Tags<input name="tags" maxlength="1000" value="${esc(item.tags.join(", "))}"></label><button class="button">Save Changes</button></form>`
      : "";
  const source = state.readOnly ? item.media_url : item.file_url;
  const commentForm = state.readOnly
    ? ""
    : `<form id="comment-form" class="edit-form"><input type="hidden" name="reply_to"><label id="reply-label">Add context<textarea name="text" maxlength="${MAX_COMMENT_BYTES}" aria-describedby="comment-limit" required></textarea></label><small id="comment-limit">Up to 8 KiB of UTF-8 text (8,192 bytes).</small><button class="button">Post Comment</button></form>`;
  const favorite = state.readOnly
    ? ""
    : `<button class="button favorite-action" data-favorite="${item.id}" data-active="${item.favorite}">${item.favorite ? "★ Remove Favorite" : "☆ Add Favorite"}</button>`;
  el("inspector-body").innerHTML =
    `<div class="inspector-grid"><div>${item.kind === "video" ? `<video class="hero-media" controls preload="none" src="${source}"></video>` : `<img class="hero-media" src="${source}" alt="${esc(item.name)}">`}</div><aside><div class="info-table"><div class="info-row"><span>Kind</span><span>${item.kind}</span></div><div class="info-row"><span>Size</span><span>${size(item.file_size)}</span></div><div class="info-row"><span>Views</span><span>${item.hits}</span></div><div class="info-row"><span>Uploader</span><span>${esc(item.uploader || "Unknown")}</span></div><div class="info-row"><span>Indexed</span><span>${new Date(item.created_at).toLocaleString()}</span></div><div class="info-row"><span>Path</span><span>${esc(item.path.replaceAll("$", "/"))}</span></div></div><div class="tag-line">${tagLinks(item.tags)}</div>${favorite}${edit}</aside></div><section class="comments"><div class="section-title"><h3>COMMENTS</h3></div><div id="comment-list">${commentTree(item.comments) || "<p>No comments yet.</p>"}</div>${commentForm}</section>`;
  el("inspector").showModal();
  state.inspectorHash = new URLSearchParams(location.hash.split("?")[1]).get("image") === String(id) ? location.hash : null;
  if (commentID) {
    const target = el(`comment-${commentID}`);
    if (target) {
      target.classList.add("comment-highlight");
      target.scrollIntoView({ block: "center" });
      target.focus({ preventScroll: true });
    }
  }
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
    comments.text.addEventListener("input", () => {
      const bytes = new TextEncoder().encode(comments.text.value.trim()).length;
      comments.text.setCustomValidity(bytes > MAX_COMMENT_BYTES ? "Comment exceeds 8 KiB (8,192 UTF-8 bytes)." : "");
    });
    el("comment-list").onclick = (event) => {
      if (event.target.dataset.reply) {
        comments.reply_to.value = event.target.dataset.reply;
        el("reply-label").firstChild.textContent =
          `Reply to comment #${event.target.dataset.reply}`;
      }
    };
    comments.onsubmit = async (event) => {
      event.preventDefault();
      if (!comments.reportValidity()) return;
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
  const routeHash = location.hash;
  try {
    if (state.view === "home") await renderHome();
    else if (state.view === "tags") await renderTags();
    else if (state.view === "explorer")
      await renderExplorer(state.folder || "");
    else if (state.view === "users") await renderUsers();
    else if (state.view === "profile") await renderProfile();
    else if (["library", "untagged", "favorites"].includes(state.view))
      await renderLibrary(
        state.view === "untagged",
        state.view === "favorites",
      );
    else throw new Error("Unknown page");
  } catch (error) {
    if (location.hash !== routeHash) return;
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
function navigate(view) {
  const hash = `#/${view}`;
  if (location.hash === hash) readRoute();
  else location.hash = hash;
}
async function readRoute() {
  const routeHash = location.hash;
  const [path, query = ""] = location.hash.slice(1).split("?");
  const params = new URLSearchParams(query);
  const profile = /^\/users\/([1-9][0-9]*)$/.exec(path);
  const view = profile ? "profile" : path.replace(/^\//, "") || "home";
  state.view = view;
  state.userID = profile ? Number(profile[1]) : null;
  state.commentCursor = params.get("cursor") || "";
  state.userQuery = view === "users" ? params.get("q") || "" : "";
  state.page = Math.max(1, Math.min(1000000, Math.floor(Number(params.get("page")) || 1)));
  state.tag = params.get("tag") || "";
  state.query = params.get("q") || "";
  el("search").value = view === "users" ? "" : state.query;
  if (el("inspector").open && !params.has("image")) el("inspector").close();
  await render();
  if (location.hash !== routeHash) return;
  if (/^[1-9][0-9]*$/.test(params.get("image") || "")) {
    try {
      const commentID = /^[1-9][0-9]*$/.test(params.get("comment") || "") ? params.get("comment") : null;
      await inspect(params.get("image"), commentID);
    } catch (error) {
      notice(error.message, true);
    }
  }
}
addEventListener("hashchange", () => { if (state.me) readRoute(); });
document.addEventListener("click", async (event) => {
  const target = event.target.closest(
    "button,[data-image],[data-tag],[data-folder],[data-preview],[data-document]",
  );
  if (!target) return;
  if (target.dataset.searchHelp) {
    el("search-help").showModal();
    return;
  }
  if (target.dataset.view) {
    setDrawer(false);
    navigate(target.dataset.view);
  }
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
    location.hash = `#/library?${new URLSearchParams({ tag: target.dataset.tag })}`;
  }
  if (target.dataset.page) {
    location.hash = `#/${state.view}?${new URLSearchParams({ page: target.dataset.page, q: state.query, tag: state.tag })}`;
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
  location.hash = `#/library?${new URLSearchParams({ q: el("search").value.trim() })}`;
});
el("search").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    location.hash = `#/library?${new URLSearchParams({ q: event.target.value.trim() })}`;
  }
});
document.addEventListener("keydown", (event) => {
  if ((event.key !== "Enter" && event.key !== " ") || !event.target.dataset.image) return;
  event.preventDefault();
  inspect(event.target.dataset.image);
});
document.addEventListener("error", (event) => {
  if (event.target.classList?.contains("video-thumbnail")) event.target.remove();
}, true);
drawerToggle.addEventListener("click", () => {
  setDrawer(!document.body.classList.contains("drawer-open"));
});
drawerBackdrop.addEventListener("click", () => {
  setDrawer(false);
  drawerToggle.focus();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && document.body.classList.contains("drawer-open")) {
    setDrawer(false);
    drawerToggle.focus();
  }
});
mobileViewport.addEventListener("change", () => setDrawer(false));
el("back").onclick = () => {
  history.back();
};
el("forward").onclick = () => {
  history.forward();
};
el("inspector").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});
el("document-reader").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});
el("password-reset").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});
el("password-reset").addEventListener("close", () => {
  el("password-reset-form").reset();
  el("password-reset-form").querySelector(".form-error").textContent = "";
});
el("search-help").addEventListener("click", (event) => {
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
el("inspector").addEventListener("close", () => {
  if (state.inspectorHash && state.inspectorHash === location.hash) {
    const [path, query] = location.hash.split("?");
    const params = new URLSearchParams(query);
    params.delete("image");
    params.delete("comment");
    history.replaceState(null, "", path + (params.size ? `?${params}` : ""));
  }
  state.inspectorHash = null;
});
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
    await refreshMe();
    await readRoute();
  } catch (error) {
    notice(error.message, true);
  }
})();
