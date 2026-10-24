import MarkdownIt from './vendor/markdown-it.mjs';

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true });
// API replies often contain identifiers or Japanese text next to underscores.
// Keep underscores literal while retaining asterisk-based Markdown emphasis.
markdown.inline.ruler.before('emphasis', 'literal_underscore', (state, silent) => {
  if (state.src.charCodeAt(state.pos) !== 95) return false;
  if (!silent) state.pending += '_';
  state.pos += 1;
  return true;
});
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
