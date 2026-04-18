#!/usr/bin/env python3
"""
Configuration GUI for the Fabric Business Documentation Agent.

No extra packages required — uses Python's built-in tkinter.

Run with:
    uv run python config_gui.py      (recommended)
    python config_gui.py             (plain Python)
    double-click  config_gui.bat     (Windows)
"""
from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

ROOT_DIR = Path(__file__).parent
ENV_PATH = ROOT_DIR / ".env"

_PAD  = {"padx": 8, "pady": 3}
_HINT = {"foreground": "#666", "font": ("TkDefaultFont", 8), "wraplength": 430}
_EW   = 38   # entry width (chars)


# ─────────────────────────────────────────────────────────────
# .env I/O
# ─────────────────────────────────────────────────────────────

def _load_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, _, v = s.partition("=")
                result[k.strip()] = v.strip()
    return result


def _save_env(path: Path, values: dict[str, str]) -> None:
    SECTIONS: list[tuple[str, list[str]]] = [
        ("# ── LLM provider", [
            "LLM_PROVIDER", "LLM_MODEL",
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
            "OLLAMA_BASE_URL", "EMBEDDING_MODEL",
        ]),
        ("# ── Input / output", [
            "ARTIFACT_TYPES", "GITHUB_REPO_URL",
            "OUTPUT_DIR", "CONTEXT_FILE", "PROMPTS_DIR",
        ]),
        ("# ── Purpose enrichment – Jira", [
            "JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY",
        ]),
        ("# ── Wiki publishing", [
            "PUBLISH_WIKI", "WIKI_TYPE",
            "AZDO_ORG", "AZDO_PROJECT", "AZDO_WIKI_ID",
            "AZDO_PAT", "AZDO_WIKI_PATH_PREFIX",
            "CONFLUENCE_URL", "CONFLUENCE_SPACE_KEY", "CONFLUENCE_EMAIL",
            "CONFLUENCE_API_TOKEN", "CONFLUENCE_PARENT_PAGE_ID",
        ]),
    ]
    lines: list[str] = []
    for header, keys in SECTIONS:
        rows = [(k, values[k]) for k in keys if values.get(k)]
        if rows:
            if lines:
                lines.append("")
            lines.append(header)
            for k, v in rows:
                lines.append(f"{k}={v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────

class ConfigApp:
    """Tabbed .env editor for business users."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Fabric Doc Agent — Configuration")
        root.resizable(False, False)

        self._vars: dict[str, tk.Variable] = {}
        self._env = _load_env(ENV_PATH)

        nb = ttk.Notebook(root, padding=2)
        nb.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        self._build_llm_tab(nb)
        self._build_files_tab(nb)
        self._build_tickets_tab(nb)
        self._build_wiki_tab(nb)

        # ── bottom bar
        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=10, pady=8)
        self._status = tk.StringVar()
        ttk.Label(bar, textvariable=self._status, foreground="#2a7a2a").pack(side="left")
        ttk.Button(bar, text="Cancel", command=root.destroy).pack(side="right", padx=(4, 0))
        ttk.Button(bar, text="Save", width=14, command=self._save).pack(side="right")

    # ── low-level helpers ─────────────────────────────────────

    def _sv(self, key: str, default: str = "") -> tk.StringVar:
        sv = tk.StringVar(value=self._env.get(key, default))
        self._vars[key] = sv
        return sv

    def _bv(self, key: str) -> tk.BooleanVar:
        raw = self._env.get(key, "").lower()
        bv = tk.BooleanVar(value=raw in ("true", "1", "yes"))
        self._vars[key] = bv
        return bv

    def _lframe(self, parent: tk.Widget, title: str) -> ttk.LabelFrame:
        """Create (but do not pack) a labelled group frame."""
        f = ttk.LabelFrame(parent, text=f"  {title}  ", padding=(8, 6))
        f.columnconfigure(1, weight=1)
        return f

    def _row(self, parent: ttk.LabelFrame, row: int, label: str, key: str,
             hint: str = "", secret: bool = False, browse: str = "") -> None:
        """Add a label + entry (+ optional browse button + hint) to a LabelFrame."""
        ttk.Label(parent, text=label, anchor="w").grid(
            row=row, column=0, sticky="w", **_PAD)
        sv = self._sv(key)
        ttk.Entry(parent, textvariable=sv, width=_EW, show="•" if secret else ""
                  ).grid(row=row, column=1, sticky="ew", **_PAD)
        if browse:
            ttk.Button(
                parent, text="…", width=3,
                command=lambda k=key, m=browse: self._pick(k, m),
            ).grid(row=row, column=2, sticky="w", padx=(0, 6), pady=3)
        if hint:
            ttk.Label(parent, text=hint, **_HINT).grid(
                row=row + 1, column=1, columnspan=2,
                sticky="w", padx=8, pady=(0, 4))

    def _pick(self, key: str, mode: str) -> None:
        sv = self._vars.get(key)
        if not isinstance(sv, tk.StringVar):
            return
        initial = sv.get() or str(ROOT_DIR)
        path = (filedialog.askdirectory(initialdir=initial, title="Select folder")
                if mode == "dir"
                else filedialog.askopenfilename(initialdir=initial, title="Select file"))
        if path:
            sv.set(path)

    # ── Tab 1: LLM Provider ───────────────────────────────────

    def _build_llm_tab(self, nb: ttk.Notebook) -> None:
        outer = ttk.Frame(nb, padding=6)
        nb.add(outer, text="  LLM Provider  ")

        # provider + model (always visible)
        pf = self._lframe(outer, "Provider")
        pf.pack(fill="x", pady=(4, 0))

        ttk.Label(pf, text="LLM Provider", anchor="w").grid(
            row=0, column=0, sticky="w", **_PAD)
        self._prov_var = self._sv("LLM_PROVIDER", "local")
        ttk.Combobox(
            pf, textvariable=self._prov_var, state="readonly",
            width=_EW - 2,
            values=["local", "anthropic", "openai", "ollama"],
        ).grid(row=0, column=1, sticky="ew", **_PAD)
        ttk.Label(
            pf,
            text="local = free, uses the Claude CLI installed on this machine  |  "
                 "anthropic / openai / ollama = need an API key or running service",
            **_HINT,
        ).grid(row=1, column=1, sticky="w", padx=8, pady=(0, 4))

        ttk.Label(pf, text="Model Override", anchor="w").grid(
            row=2, column=0, sticky="w", **_PAD)
        ttk.Entry(pf, textvariable=self._sv("LLM_MODEL"), width=_EW).grid(
            row=2, column=1, sticky="ew", **_PAD)
        ttk.Label(
            pf,
            text="Leave blank for the provider default  "
                 "(claude-sonnet-4-6 / gpt-4o-mini / llama3.2)",
            **_HINT,
        ).grid(row=3, column=1, sticky="w", padx=8, pady=(0, 4))

        # provider-specific panels (mutually exclusive)
        self._f_local = self._lframe(outer, "Local Claude CLI")
        ttk.Label(
            self._f_local,
            text="No API key required.\n"
                 "The Claude CLI must be installed on this machine — download from claude.ai/code",
            foreground="#444",
        ).grid(row=0, column=0, columnspan=2, sticky="w", **_PAD)

        self._f_anthropic = self._lframe(outer, "Anthropic")
        self._row(self._f_anthropic, 0, "API Key", "ANTHROPIC_API_KEY",
                  "Required. Create one at  console.anthropic.com", secret=True)

        self._f_openai = self._lframe(outer, "OpenAI")
        self._row(self._f_openai, 0, "API Key", "OPENAI_API_KEY",
                  "Required. Create one at  platform.openai.com", secret=True)

        self._f_ollama = self._lframe(outer, "Ollama")
        self._row(self._f_ollama, 0, "Ollama Base URL", "OLLAMA_BASE_URL",
                  "Default: http://localhost:11434   Ollama must be running locally")

        # embeddings panel (openai / ollama only)
        self._f_embed = self._lframe(outer, "Embeddings (RAG context)")
        self._row(self._f_embed, 0, "Embedding Model", "EMBEDDING_MODEL",
                  "Optional override.  "
                  "Defaults: text-embedding-3-small (OpenAI) / nomic-embed-text (Ollama)")

        self._prov_var.trace_add("write", lambda *_: self._refresh_prov())
        self._refresh_prov()

    def _refresh_prov(self) -> None:
        p = self._prov_var.get()
        for f in (self._f_local, self._f_anthropic, self._f_openai,
                  self._f_ollama, self._f_embed):
            f.pack_forget()
        show = {
            "local":     [self._f_local],
            "anthropic": [self._f_anthropic],
            "openai":    [self._f_openai, self._f_embed],
            "ollama":    [self._f_ollama, self._f_embed],
        }.get(p, [])
        for f in show:
            f.pack(fill="x", pady=(6, 0))

    # ── Tab 2: Files & Folders ────────────────────────────────

    def _build_files_tab(self, nb: ttk.Notebook) -> None:
        outer = ttk.Frame(nb, padding=6)
        nb.add(outer, text="  Files & Folders  ")

        # artifact types as checkboxes
        af = self._lframe(outer, "Artifact Types to Scan")
        af.pack(fill="x", pady=(4, 0))
        ttk.Label(
            af, text="Select which file types the agent should process:",
            foreground="#444",
        ).grid(row=0, column=0, columnspan=4, sticky="w", **_PAD)

        self._art_vars: dict[str, tk.BooleanVar] = {}
        enabled = set(
            (self._env.get("ARTIFACT_TYPES") or "pipeline,notebook,dataflow").split(",")
        )
        TYPES = [
            ("pipeline",      "Fabric Pipeline"),
            ("notebook",      "Fabric Notebook"),
            ("dataflow",      "Dataflow Gen2"),
            ("powerautomate", "Power Automate"),
        ]
        for i, (key, label) in enumerate(TYPES):
            bv = tk.BooleanVar(value=key in enabled)
            self._art_vars[key] = bv
            ttk.Checkbutton(af, text=label, variable=bv).grid(
                row=1 + i // 2, column=i % 2, sticky="w", padx=16, pady=2)

        # paths
        pf = self._lframe(outer, "Paths")
        pf.pack(fill="x", pady=(8, 0))
        self._row(pf, 0, "Output Folder", "OUTPUT_DIR",
                  "Folder where the generated .md files are written.  Default: ./output",
                  browse="dir")
        self._row(pf, 2, "Context File", "CONTEXT_FILE",
                  "Optional plain-text file describing your organisation or data platform. "
                  "Its content is added to every LLM prompt so the agent uses your terminology.",
                  browse="file")
        self._row(pf, 4, "Custom Prompts Folder", "PROMPTS_DIR",
                  "Optional. Folder of per-section prompt templates.  Default: ./prompts",
                  browse="dir")

        # source repo
        sf = self._lframe(outer, "Source Repository (optional)")
        sf.pack(fill="x", pady=(8, 0))
        self._row(sf, 0, "GitHub Repository URL", "GITHUB_REPO_URL",
                  "If set, the agent clones this repo before scanning. "
                  "Leave blank to scan a local folder with  --src.")

    # ── Tab 3: Ticket Integration ─────────────────────────────

    def _build_tickets_tab(self, nb: ttk.Notebook) -> None:
        outer = ttk.Frame(nb, padding=6)
        nb.add(outer, text="  Ticket Integration  ")

        jf = self._lframe(outer, "Jira (optional)")
        jf.pack(fill="x", pady=(4, 0))
        ttk.Label(
            jf,
            text="When configured, the agent searches Jira for work items linked to each "
                 "artifact and uses their descriptions to write a more accurate Purpose section.",
            foreground="#444", wraplength=490,
        ).grid(row=0, column=0, columnspan=3, sticky="w", **_PAD)
        self._row(jf, 1, "Jira Base URL", "JIRA_URL",
                  "e.g.  https://mycompany.atlassian.net")
        self._row(jf, 3, "Email", "JIRA_EMAIL",
                  "Your Atlassian account email address")
        self._row(jf, 5, "API Token", "JIRA_API_TOKEN",
                  "Create one at  id.atlassian.com → Security → API tokens",
                  secret=True)
        self._row(jf, 7, "Project Key (optional)", "JIRA_PROJECT_KEY",
                  "Restrict the search to one project,  e.g.  PROJ")

        af = self._lframe(outer, "Azure DevOps Work Items (optional)")
        af.pack(fill="x", pady=(8, 0))
        ttk.Label(
            af,
            text="Azure DevOps work items and pull requests are also searched when Azure DevOps "
                 "is configured.\n\n"
                 "Fill in Organisation, Project, and PAT on the  Wiki Publishing  tab — those "
                 "same credentials are used for the work-item search automatically.",
            foreground="#444", wraplength=490,
        ).grid(row=0, column=0, columnspan=2, sticky="w", **_PAD)

    # ── Tab 4: Wiki Publishing ────────────────────────────────

    def _build_wiki_tab(self, nb: ttk.Notebook) -> None:
        outer = ttk.Frame(nb, padding=6)
        nb.add(outer, text="  Wiki Publishing  ")

        # enable toggle
        ef = self._lframe(outer, "Enable")
        ef.pack(fill="x", pady=(4, 0))
        self._pub_var = self._bv("PUBLISH_WIKI")
        ttk.Checkbutton(
            ef,
            text="Push generated pages to a wiki immediately after each run",
            variable=self._pub_var,
            command=self._refresh_wiki,
        ).grid(row=0, column=0, columnspan=2, sticky="w", **_PAD)

        # backend selector
        tf = self._lframe(outer, "Backend")
        tf.pack(fill="x", pady=(8, 0))
        ttk.Label(tf, text="Wiki Type", anchor="w").grid(row=0, column=0, sticky="w", **_PAD)
        self._wtype_var = self._sv("WIKI_TYPE", "azuredevops")
        self._wtype_cb = ttk.Combobox(
            tf, textvariable=self._wtype_var, state="readonly",
            width=_EW - 2, values=["azuredevops", "confluence"],
        )
        self._wtype_cb.grid(row=0, column=1, sticky="ew", **_PAD)
        ttk.Label(
            tf,
            text="azuredevops = Azure DevOps project wiki   |   confluence = Atlassian Confluence",
            **_HINT,
        ).grid(row=1, column=1, sticky="w", padx=8, pady=(0, 4))
        self._wtype_var.trace_add("write", lambda *_: self._refresh_wiki_type())

        # Azure DevOps fields
        self._f_azdo = self._lframe(outer, "Azure DevOps")
        self._row(self._f_azdo, 0, "Organisation", "AZDO_ORG",
                  "Organisation name from your Azure DevOps URL,  e.g.  my-organisation")
        self._row(self._f_azdo, 2, "Project", "AZDO_PROJECT",
                  "Project name,  e.g.  my-project")
        self._row(self._f_azdo, 4, "Wiki ID", "AZDO_WIKI_ID",
                  "Wiki identifier shown in the URL,  e.g.  my-project.wiki")
        self._row(self._f_azdo, 6, "Personal Access Token", "AZDO_PAT",
                  "Create a PAT with  Wiki (Read & Write)  scope.", secret=True)
        self._row(self._f_azdo, 8, "Path Prefix (optional)", "AZDO_WIKI_PATH_PREFIX",
                  "Nest all generated pages under this wiki path,  e.g.  /Fabric Docs")

        # Confluence fields
        self._f_conf = self._lframe(outer, "Confluence")
        self._row(self._f_conf, 0, "Confluence URL", "CONFLUENCE_URL",
                  "e.g.  https://mycompany.atlassian.net")
        self._row(self._f_conf, 2, "Space Key", "CONFLUENCE_SPACE_KEY",
                  "e.g.  FABRIC")
        self._row(self._f_conf, 4, "Email", "CONFLUENCE_EMAIL",
                  "Your Atlassian account email address")
        self._row(self._f_conf, 6, "API Token", "CONFLUENCE_API_TOKEN",
                  "Create one at  id.atlassian.com → Security → API tokens", secret=True)
        self._row(self._f_conf, 8, "Parent Page ID (optional)", "CONFLUENCE_PARENT_PAGE_ID",
                  "Numeric ID of the parent page under which all generated pages are nested")

        self._refresh_wiki()

    def _refresh_wiki(self) -> None:
        enabled = self._pub_var.get()
        self._wtype_cb.configure(state="readonly" if enabled else "disabled")
        if enabled:
            self._refresh_wiki_type()
        else:
            self._f_azdo.pack_forget()
            self._f_conf.pack_forget()

    def _refresh_wiki_type(self) -> None:
        if not self._pub_var.get():
            return
        if self._wtype_var.get() == "azuredevops":
            self._f_conf.pack_forget()
            self._f_azdo.pack(fill="x", pady=(8, 0))
        else:
            self._f_azdo.pack_forget()
            self._f_conf.pack(fill="x", pady=(8, 0))

    # ── collect & save ────────────────────────────────────────

    def _collect(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for key, var in self._vars.items():
            result[key] = ("true" if var.get() else "") if isinstance(var, tk.BooleanVar) \
                          else var.get().strip()
        chosen = [k for k, bv in self._art_vars.items() if bv.get()]
        result["ARTIFACT_TYPES"] = ",".join(chosen) if chosen else "pipeline,notebook,dataflow"
        return result

    def _save(self) -> None:
        values = self._collect()
        if not values.get("LLM_PROVIDER"):
            messagebox.showwarning("Required", "Please select an LLM Provider.")
            return
        try:
            _save_env(ENV_PATH, values)
            self._status.set("✓  Saved to .env")
            self.root.after(4000, lambda: self._status.set(""))
        except Exception as exc:
            messagebox.showerror("Save error", str(exc))


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

def main() -> None:
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.25)   # sharper on Windows HiDPI
    except tk.TclError:
        pass
    ConfigApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
