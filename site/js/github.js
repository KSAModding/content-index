export const INDEX_REPOSITORY = "KSAModding/content-index";
export const URL_LIMIT = 8000;
const REPOSITORY = /^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\/[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$/;

export function listingPath(id) {
  return `listings/${id}.toml`;
}

export function rawListingUrl(id) {
  return `https://raw.githubusercontent.com/${INDEX_REPOSITORY}/main/${listingPath(encodeURIComponent(id))}`;
}

export function newFileUrl(id, text) {
  const base = `https://github.com/${INDEX_REPOSITORY}/new/main?filename=${listingPath(encodeURIComponent(id))}`;
  const filled = `${base}&value=${encodeURIComponent(text)}`;
  return filled.length <= URL_LIMIT ? { url: filled, filled: true } : { url: base, filled: false };
}

export function editUrl(id) {
  return `https://github.com/${INDEX_REPOSITORY}/edit/main/${listingPath(encodeURIComponent(id))}`;
}

export function repositoryApiUrl(repository) {
  return REPOSITORY.test(repository) ? `https://api.github.com/repos/${repository}` : null;
}

export function prefillFromRepository(answer) {
  const license = answer.license && answer.license.spdx_id;
  const htmlUrl = typeof answer.html_url === "string" ? answer.html_url : "";
  return {
    name: typeof answer.name === "string" ? answer.name : "",
    abstract: typeof answer.description === "string" ? answer.description.trim() : "",
    license: license && license !== "NOASSERTION" && license !== "OTHER" ? license : "",
    repository: htmlUrl,
    bugtracker: htmlUrl && answer.has_issues ? `${htmlUrl}/issues` : "",
    owner: answer.owner && typeof answer.owner.login === "string" ? answer.owner.login : "",
    organization: Boolean(answer.owner && answer.owner.type === "Organization"),
    fork: Boolean(answer.fork),
  };
}
