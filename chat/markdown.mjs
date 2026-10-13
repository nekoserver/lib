import MarkdownIt from './vendor/markdown-it.mjs';

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true });

export function renderMarkdown(source) {
  return markdown.render(String(source ?? ''));
}

export function showMarkdown(element, source) {
  // Only parser-generated HTML is inserted. Raw HTML and unsafe link schemes
  // are disabled by the renderer; code and HTML in answers remain escaped.
  element.innerHTML = renderMarkdown(source);
}
