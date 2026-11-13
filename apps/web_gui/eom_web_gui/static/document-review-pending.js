// Tab storage is only a replay reference. Source bytes, guidance and authority
// remain in the upload boundary and the authenticated API, never this record.
const PREFIX = "eom:document-review:pending:1:";
const KEYS = ["intentKey", "contentKey", "setKey", "questionKey", "solutionKey"];
const SHAPE = ["schema_version", "fingerprint", "kind", ...KEYS, "intentId", "reviewSetId"].sort().join();
const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const KEY_PREFIXES = ["studio:pdf-review:intent:", "studio:pdf-review:content:",
  "studio:paired-review:set:", "studio:paired-review:question:", "studio:paired-review:solution:"];
const INVALID = "이전 자료 등록 요청을 안전하게 복원하지 못했습니다. 새 검토를 시작하지 말고 관리자에게 알려 주세요.";

function checked(value) {
  if (!value || Object.keys(value).sort().join() !== SHAPE
    || value.schema_version !== "document-review-pending/1.0"
    || !["SINGLE", "PAIRED"].includes(value.kind)
    || !/^sha256:[0-9a-f]{64}$/.test(value.fingerprint)
    || !KEYS.every((key, index) => new RegExp(`^${KEY_PREFIXES[index]}${UUID}$`).test(value[key]))
    || (value.intentId !== null && !/^pdfreviewintent_[0-9a-f]{32}$/.test(value.intentId))
    || (value.reviewSetId !== null && !/^docreviewset_[0-9a-f]{32}$/.test(value.reviewSetId))
    || (value.kind === "SINGLE" ? value.reviewSetId !== null : value.intentId !== null)) {
    throw new Error(INVALID);
  }
  return Object.freeze({...value});
}

export async function documentReviewRequestFingerprint(value) {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, "0")).join("")}`;
}

export function createDocumentReviewPendingStore(getStorage = () => globalThis.sessionStorage) {
  const storage = () => {
    const value = getStorage();
    if (!value) throw new Error("이 브라우저에서 자료 등록 요청을 보관할 수 없습니다. 다른 브라우저로 다시 시도해 주세요.");
    return value;
  };
  const storageKey = owner => {
    if (!/^operator_[0-9a-f]{32}$/.test(owner)) throw new Error(INVALID);
    return PREFIX + owner;
  };
  return {
    read(owner) {
      const raw = storage().getItem(storageKey(owner));
      if (raw === null) return null;
      if (raw.length > 4096) throw new Error(INVALID);
      return checked(JSON.parse(raw));
    },
    write(owner, value) {
      const record = checked(value);
      storage().setItem(storageKey(owner), JSON.stringify(record));
      return record;
    },
    clear(owner, value) {
      const current = this.read(owner);
      if (current?.fingerprint === value.fingerprint && current.intentKey === value.intentKey
        && current.setKey === value.setKey) storage().removeItem(storageKey(owner));
    },
  };
}
