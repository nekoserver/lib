/** A parent may supply colors, never CSS selectors, URLs, or stream commands. */
export function applyEmbedTheme(root, data, css = CSS) {
  if (data?.type !== 'conversation-theme' || !data.palette || typeof data.palette !== 'object') return false;
  const keys = ['bg', 'fg', 'muted', 'input', 'border', 'accent'];
  for (const key of keys) {
    const value = data.palette[key];
    if (typeof value !== 'string' || value.length > 128 || !css.supports('color', value)) return false;
  }
  const image = data.palette.backgroundImage ?? 'none';
  if (typeof image !== 'string' || image.length > 1024 || !/^(none|(?:linear|radial)-gradient\()/i.test(image) || /url\s*\(/i.test(image) || !css.supports('background-image', image)) return false;
  for (const key of keys) root.style.setProperty('--embed-' + key, data.palette[key]);
  root.style.setProperty('--embed-background-image', image);
  return true;
}
