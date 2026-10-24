import MarkdownIt from './vendor/markdown-it.mjs';

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true });
const renderLink = markdown.renderer.rules.link_open || ((tokens, index, options, env, renderer) => renderer.renderToken(tokens, index, options));
markdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index].attrSet('target', '_blank');
  tokens[index].attrSet('rel', 'noopener noreferrer');
  return renderLink(tokens, index, options, env, renderer);
};

export function renderMarkdown(source) {
  return markdown.render(String(source ?? ''));
}

export function showMarkdown(element, source) {
  // Only parser-generated HTML is inserted. Raw HTML and unsafe link schemes
  // are disabled by the renderer; code and HTML in answers remain escaped.
  element.innerHTML = renderMarkdown(source);
}
