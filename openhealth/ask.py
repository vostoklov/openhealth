import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, TextIO, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .storage import ensure_repo_structure


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-latest"
CITATION_PATTERN = re.compile(r"\[((?:Q|T|P)\d+)\]")


@dataclass
class ContextSnippet:
    citation_id: str
    path_label: str
    content: str


@dataclass
class PromptBundle:
    system_prompt: str
    user_prompt: str
    snippets: Dict[str, ContextSnippet]
    missing_paths: List[str]


def run_ask(
    root: Path,
    question: str,
    *,
    model: Optional[str] = None,
    max_tokens: int = 900,
    stream: bool = True,
    out: Optional[TextIO] = None,
    err: Optional[TextIO] = None,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    prompt_bundle = build_prompt_bundle(root, question)
    if prompt_bundle.missing_paths:
        missing = ", ".join(prompt_bundle.missing_paths)
        err.write(
            "Missing required context files: %s. Run `python3 -m openhealth --repo-root %s refresh-contexts` and try again.\n"
            % (missing, root)
        )
        return 1

    api_key = os.environ.get("OPENHEALTH_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        render_offline_fallback(question, prompt_bundle, out)
        return 0

    try:
        answer = fetch_anthropic_answer(
            api_key=api_key,
            prompt_bundle=prompt_bundle,
            model=model or os.environ.get("OPENHEALTH_ASK_MODEL") or os.environ.get("ANTHROPIC_MODEL"),
            max_tokens=max_tokens,
            stream=stream,
            out=out,
        )
    except RuntimeError as exc:
        err.write("%s\n" % exc)
        return 1

    if not stream:
        out.write(answer.rstrip() + "\n")
    elif answer and not answer.endswith("\n"):
        out.write("\n")
    render_citations(answer, prompt_bundle.snippets, out)
    return 0


def build_prompt_bundle(root: Path, question: str) -> PromptBundle:
    paths = ensure_repo_structure(root)
    context_specs = [
        ("Q", paths.contexts / "quick-brief.md", "contexts/quick-brief.md"),
        ("T", paths.timeline_context / "current.md", "contexts/timeline/current.md"),
        ("P", paths.contexts / "profile.md", "contexts/profile.md"),
    ]
    snippets: Dict[str, ContextSnippet] = {}
    rendered_sections: List[str] = []
    missing_paths: List[str] = []
    for prefix, path, label in context_specs:
        if not path.exists():
            missing_paths.append(label)
            continue
        rendered_section, section_snippets = annotate_context_file(path, label, prefix)
        rendered_sections.append(rendered_section)
        snippets.update(section_snippets)

    system_prompt = (
        "You are the OpenHealth demo assistant. Answer only from the provided context files. "
        "Be concise, useful, and honest about uncertainty. Cite factual claims inline using the provided IDs, "
        "for example [Q1] or [T14]. If the current files do not support a claim, say so plainly."
    )
    user_prompt = "Question:\n%s\n\nContext files:\n\n%s" % (question.strip(), "\n\n".join(rendered_sections))
    return PromptBundle(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        snippets=snippets,
        missing_paths=missing_paths,
    )


def annotate_context_file(path: Path, label: str, prefix: str) -> Tuple[str, Dict[str, ContextSnippet]]:
    snippets: Dict[str, ContextSnippet] = {}
    rendered_lines = ["## %s" % label, ""]
    counter = 1
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#"):
            citation_id = "%s%s" % (prefix, counter)
            rendered_lines.append("[%s] %s" % (citation_id, raw_line))
            snippets[citation_id] = ContextSnippet(
                citation_id=citation_id,
                path_label=label,
                content=stripped,
            )
            counter += 1
        else:
            rendered_lines.append(raw_line)
    return "\n".join(rendered_lines).rstrip(), snippets


def render_offline_fallback(question: str, prompt_bundle: PromptBundle, out: TextIO) -> None:
    out.write("No Anthropic API key found. Paste this prompt into Claude Code or Cursor.\n\n")
    out.write("Question:\n%s\n\n" % question.strip())
    out.write("Instructions:\n")
    out.write("- Read the context files below.\n")
    out.write("- Answer using only this evidence.\n")
    out.write("- Cite factual claims inline with IDs like [Q1] or [T4].\n")
    out.write("- If the files are insufficient, say so clearly.\n\n")
    out.write(prompt_bundle.user_prompt.rstrip() + "\n")


def fetch_anthropic_answer(
    *,
    api_key: str,
    prompt_bundle: PromptBundle,
    model: Optional[str],
    max_tokens: int,
    stream: bool,
    out: TextIO,
) -> str:
    model_name = model or DEFAULT_ANTHROPIC_MODEL
    payload = {
        "model": model_name,
        "max_tokens": max_tokens,
        "system": prompt_bundle.system_prompt,
        "messages": [{"role": "user", "content": prompt_bundle.user_prompt}],
    }
    if stream:
        payload["stream"] = True
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        ANTHROPIC_API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            if stream:
                return _read_streaming_response(response, out)
            body = json.loads(response.read().decode("utf-8"))
            return "".join(
                block.get("text", "")
                for block in body.get("content", [])
                if block.get("type") == "text"
            )
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError("Anthropic request failed (%s): %s" % (exc.code, body))
    except URLError as exc:
        raise RuntimeError("Anthropic request failed: %s" % exc)


def _read_streaming_response(response, out: TextIO) -> str:
    chunks: List[str] = []
    for raw_line in response:
        line = raw_line.decode("utf-8").strip()
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if not payload:
            continue
        event = json.loads(payload)
        if event.get("type") == "content_block_delta" and event.get("delta", {}).get("type") == "text_delta":
            text = event["delta"]["text"]
            chunks.append(text)
            out.write(text)
            out.flush()
        elif event.get("type") == "error":
            raise RuntimeError("Anthropic stream error: %s" % event)
    return "".join(chunks)


def render_citations(answer: str, snippets: Dict[str, ContextSnippet], out: TextIO) -> None:
    cited_ids = []
    seen = set()
    for match in CITATION_PATTERN.findall(answer):
        citation_id = match
        if citation_id in snippets and citation_id not in seen:
            seen.add(citation_id)
            cited_ids.append(citation_id)
    if not cited_ids:
        out.write("\nCited records: none returned.\n")
        return

    out.write("\nCited records:\n")
    for citation_id in cited_ids:
        snippet = snippets[citation_id]
        out.write("- [%s] %s :: %s\n" % (citation_id, snippet.path_label, snippet.content))
