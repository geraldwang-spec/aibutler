/* One-time, idempotent migration of learning-only styles to semantic palette tokens.
   Shared legacy and BODY styles are deliberately excluded. */
const fs = require('fs');
const files = ['product', 'question-workspace', 'workspace-decor', 'workspace-order',
  'calendar-summary', 'planner-goals', 'milestone-journey', 'subject-workspace',
  'chat-async', 'learning-charts', 'draft-batch'];
function hsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), delta = max - min;
  const l = (max + min) / 2;
  if (!delta) return [0, 0, l];
  const s = delta / (1 - Math.abs(2 * l - 1));
  let h = max === r ? ((g - b) / delta + (g < b ? 6 : 0)) : max === g ? ((b - r) / delta + 2) : ((r - g) / delta + 4);
  return [h * 60, s, l];
}
function token(r, g, b, alpha, property, original) {
  const [h, saturation, lightness] = hsl(r, g, b);
  const neutral = saturation < .12;
  const family = neutral ? 'neutral' : h < 15 || h >= 345 ? 'red' : h < 75 ? 'amber' : h < 175 ? 'green' : h < 235 ? 'blue' : 'accent';
  const text = property === 'color' || property === 'fill' || /(?:ink|muted|text)$/.test(property);
  const border = /border|outline/.test(property);
  let name;
  if (text) {
    name = lightness > .94 ? 'on-accent' : neutral ? (lightness > .55 ? 'muted' : 'ink') : `${family}-text`;
  } else if (border) {
    name = neutral ? 'border' : `${family}-border`;
  } else if (family === 'neutral') {
    name = lightness > .96 ? 'surface' : lightness > .82 ? 'surface-alt' : lightness > .6 ? 'border' : 'ink';
  } else {
    name = `${family}-${lightness > .85 ? 'soft' : lightness > .65 ? 'medium' : 'strong'}`;
  }
  const variable = `var(--theme-${name}, ${original})`;
  if (alpha < 1) {
    // The fallback already contains alpha, so use an opaque fallback inside the mix.
    const opaque = '#' + [r, g, b].map(value => value.toString(16).padStart(2, '0')).join('');
    return `color-mix(in srgb, var(--theme-${name}, ${opaque}) ${+(alpha * 100).toFixed(2)}%, transparent)`;
  }
  return variable;
}
function convertColors(source) {
  source = source.replace(/(^|[;{])\s*([\w-]+)\s*:\s*([^;{}]+)/g, (whole, separator, property, value) => {
    // Preserve URL contents and quoted strings, such as decorative illustrations.
    const protectedValues = [];
    value = value.replace(/url\([^)]*\)|'[^']*'|"[^"]*"/g, entry => `__PALETTE_KEEP_${protectedValues.push(entry) - 1}__`);
    value = value.replace(/#[a-f\d]{8}\b|#[a-f\d]{6}\b|#[a-f\d]{4}\b|#[a-f\d]{3}\b|\b(?:white|black)\b|rgba?\([\d.,\s]+\)/gi, original => {
      let r, g, b, alpha = 1;
      if (original.toLowerCase() === 'white') r = g = b = 255;
      else if (original.toLowerCase() === 'black') r = g = b = 0;
      else if (original.startsWith('#')) {
        let hex = original.slice(1);
        if (hex.length <= 4) hex = [...hex].map(c => c + c).join('');
        [r, g, b] = [0, 2, 4].map(offset => parseInt(hex.slice(offset, offset + 2), 16));
        if (hex.length === 8) alpha = parseInt(hex.slice(6), 16) / 255;
      } else {
        [r, g, b, alpha = 1] = original.match(/[\d.]+/g).map(Number);
      }
      return token(r, g, b, alpha, property, original);
    });
    value = value.replace(/__PALETTE_KEEP_(\d+)__/g, (_, index) => protectedValues[Number(index)]);
    return `${separator}${property}:${value}`;
  });
  return source;
}
module.exports = {convertColors};
if (require.main === module) {
  for (const file of files) {
    const path = `static/css/${file}.css`;
    const source = fs.readFileSync(path, 'utf8');
    if (source.startsWith('/* Semantic workspace palette')) continue;
    fs.writeFileSync(path, '/* Semantic workspace palette; legacy/BODY sheets remain unchanged. */\n' + convertColors(source));
  }
}
