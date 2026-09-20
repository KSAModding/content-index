export const ICON = "icon";
export const DESCRIPTION = "description";

export const LIMITS = {
  [ICON]: { low: 256, high: 1024, ratio: 2, cap: 256 * 1024 },
  [DESCRIPTION]: { low: 1, high: 2048, ratio: null, cap: 1024 * 1024 },
};

// A local file over the cap is still measured up to this many times the cap, so the author sees its size next to the error.
export const MEASURE_FACTOR = 4;

export const RECORD_KEYS = ["id", "url", "sha256", "width", "height", "size", "license", "attribution", "source"];

export class Invalid extends Error {}

export function records(document) {
  const images = document && document.images;
  if (!images || typeof images !== "object" || Array.isArray(images)) {
    return [];
  }
  const found = [];
  const icon = images[ICON];
  if (icon && typeof icon === "object" && !Array.isArray(icon)) {
    found.push([`images.${ICON}`, ICON, icon]);
  }
  const entries = images[DESCRIPTION];
  if (Array.isArray(entries)) {
    entries.forEach((record, index) => {
      if (record && typeof record === "object" && !Array.isArray(record)) {
        found.push([`images.${DESCRIPTION}[${index}]`, DESCRIPTION, record]);
      }
    });
  }
  return found;
}

function ascii(bytes, start, length) {
  return String.fromCharCode(...bytes.subarray(start, start + length));
}

function need(bytes, end) {
  if (end > bytes.length) {
    throw new Invalid("the image ends early");
  }
}

function png(bytes, view) {
  let position = 8;
  let size = null;
  let animated = false;
  let pixels = false;
  while (position + 12 <= bytes.length) {
    const length = view.getUint32(position);
    const kind = ascii(bytes, position + 4, 4);
    if (position + 8 + length > bytes.length) {
      break;
    }
    if (size === null) {
      if (kind !== "IHDR" || length !== 13) {
        throw new Invalid("the PNG does not start with its header chunk");
      }
      size = [view.getUint32(position + 8), view.getUint32(position + 12)];
    } else if (kind === "acTL") {
      animated = true;
    } else if (kind === "IDAT") {
      pixels = true;
    } else if (kind === "IEND") {
      if (!pixels) {
        throw new Invalid("the PNG carries no image data");
      }
      return { format: "PNG", width: size[0], height: size[1], animated };
    }
    position += 12 + length;
  }
  throw new Invalid("the PNG ends before its IEND chunk");
}

const JPEG_FRAMES = new Set([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf]);

function jpeg(bytes, view) {
  let position = 2;
  while (position < bytes.length) {
    if (bytes[position] !== 0xff) {
      throw new Invalid("the JPEG has a broken marker");
    }
    while (position < bytes.length && bytes[position] === 0xff) {
      position += 1;
    }
    if (position >= bytes.length) {
      break;
    }
    const marker = bytes[position];
    position += 1;
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd8)) {
      continue;
    }
    if (marker === 0xd9 || marker === 0xda) {
      break;
    }
    need(bytes, position + 2);
    const length = view.getUint16(position);
    if (length < 2) {
      throw new Invalid("the JPEG has a broken segment length");
    }
    if (JPEG_FRAMES.has(marker)) {
      need(bytes, position + 7);
      return { format: "JPEG", width: view.getUint16(position + 5), height: view.getUint16(position + 3), animated: false };
    }
    position += length;
  }
  throw new Invalid("the JPEG names no frame size before its image data");
}

function webp(bytes, view) {
  const end = 8 + view.getUint32(4, true);
  if (end > bytes.length) {
    throw new Invalid("the WebP is shorter than its RIFF header says");
  }
  let position = 12;
  let canvas = null;
  let frame = null;
  let animated = false;
  while (position + 8 <= end) {
    const kind = ascii(bytes, position, 4);
    const length = view.getUint32(position + 4, true);
    if (position + 8 + length > end) {
      throw new Invalid("a WebP chunk runs past the end of the file");
    }
    const body = position + 8;
    if (kind === "VP8X") {
      if (length < 10) {
        throw new Invalid("the WebP has a broken extended header");
      }
      animated = animated || Boolean(bytes[body] & 0x02);
      const width = bytes[body + 4] | (bytes[body + 5] << 8) | (bytes[body + 6] << 16);
      const height = bytes[body + 7] | (bytes[body + 8] << 8) | (bytes[body + 9] << 16);
      canvas = [width + 1, height + 1];
    } else if (kind === "ANIM" || kind === "ANMF") {
      animated = true;
    } else if (kind === "VP8 " && frame === null) {
      if (length < 10 || bytes[body + 3] !== 0x9d || bytes[body + 4] !== 0x01 || bytes[body + 5] !== 0x2a) {
        throw new Invalid("the WebP has a broken lossy frame header");
      }
      frame = [view.getUint16(body + 6, true) & 0x3fff, view.getUint16(body + 8, true) & 0x3fff];
    } else if (kind === "VP8L" && frame === null) {
      if (length < 5 || bytes[body] !== 0x2f) {
        throw new Invalid("the WebP has a broken lossless header");
      }
      const bits = view.getUint32(body + 1, true);
      frame = [1 + (bits & 0x3fff), 1 + ((bits >>> 14) & 0x3fff)];
    }
    position += 8 + length + (length & 1);
  }
  if (frame === null && !animated) {
    throw new Invalid("the WebP carries no image");
  }
  const [width, height] = canvas || frame || [0, 0];
  return { format: "WebP", width, height, animated };
}

function startsWith(bytes, signature) {
  return signature.every((value, index) => bytes[index] === value);
}

export function inspect(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  try {
    if (startsWith(bytes, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) {
      return png(bytes, view);
    }
    if (startsWith(bytes, [0xff, 0xd8, 0xff])) {
      return jpeg(bytes, view);
    }
    if (bytes.length >= 12 && ascii(bytes, 0, 4) === "RIFF" && ascii(bytes, 8, 4) === "WEBP") {
      return webp(bytes, view);
    }
  } catch (error) {
    if (error instanceof RangeError) {
      throw new Invalid("the image ends early");
    }
    throw error;
  }
  throw new Invalid("the bytes are not PNG, JPEG or WebP");
}

export function outsideLimits(role, width, height) {
  const limits = LIMITS[role];
  const shorter = Math.min(width, height);
  const longer = Math.max(width, height);
  if (limits.ratio === null) {
    if (limits.low <= shorter && longer <= limits.high) {
      return null;
    }
    return `${width} by ${height} pixels is outside ${limits.low} to ${limits.high} per side`;
  }
  if (limits.low <= shorter && shorter <= limits.high && longer <= limits.ratio * shorter) {
    return null;
  }
  return (
    `${width} by ${height} pixels is outside the limits: the shorter side ` +
    `${limits.low} to ${limits.high}, the longer side at most ${limits.ratio} times the shorter side`
  );
}

export function centerSquare(width, height) {
  const side = Math.min(width, height);
  const left = Math.floor((width - side) / 2);
  const top = Math.floor((height - side) / 2);
  return [left, top, left + side, top + side];
}

export async function sha256(bytes) {
  const digest = new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", bytes));
  return Array.from(digest, (value) => value.toString(16).padStart(2, "0")).join("");
}

export async function measure(bytes, role) {
  const cap = LIMITS[role].cap;
  const problems = [];
  if (bytes.length > cap) {
    problems.push(`the image is larger than the cap of ${cap} bytes`);
  }
  let facts = null;
  try {
    facts = inspect(bytes);
  } catch (error) {
    if (!(error instanceof Invalid)) {
      throw error;
    }
    problems.push(error.message);
  }
  if (facts) {
    if (facts.animated) {
      problems.push(`the ${facts.format} is animated`);
    }
    const outside = outsideLimits(role, facts.width, facts.height);
    if (outside) {
      problems.push(outside);
    }
  }
  return {
    facts,
    problems,
    sha256: await sha256(bytes),
    size: bytes.length,
  };
}

export async function readCapped(response, cap) {
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.length;
    if (size > cap) {
      reader.cancel().catch(() => {});
      return null;
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let at = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, at);
    at += chunk.length;
  }
  return bytes;
}
