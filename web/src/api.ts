// Types mirror backend/app/schemas.py. All weight logic lives on the backend.

export type Item = { id: number; name: string };

export type Change = "added" | "removed" | "restored" | "reweighted";

export type OfferView = {
  offer_id: number;
  name: string;
  state: "active" | "removed";
  share: number;
  pin: number | null;
  change: Change | null;
};

export type StreamView = {
  id: number;
  name: string;
  position: number;
  has_offers: boolean;
  dirty: boolean;
  total_share: number;
  push_blocked_reason: string | null;
  offers: OfferView[];
};

export type CampaignView = { id: number; name: string; streams: StreamView[] };

export type Meta = {
  domains: Item[];
  groups: Item[];
  traffic_sources: Item[];
  default_domain_id: number | null;
  default_group_id: number | null;
  default_traffic_source_id: number | null;
};

export type CreateCampaign = {
  name: string;
  geo: string;
  offer_id: number;
  domain_id: number;
  group_id: number;
  traffic_source_id: number;
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    // FastAPI validation errors come as a list of {msg}
    const message = Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail;
    throw new ApiError(message ?? `Request failed (${response.status})`, response.status);
  }
  return data as T;
}

const streamPath = (streamId: number, offerId?: number) =>
  `/streams/${streamId}` + (offerId === undefined ? "" : `/offers/${offerId}`);

export const api = {
  meta: () => request<Meta>("GET", "/meta"),
  searchOffers: (q: string) => request<Item[]>("GET", `/offers?q=${encodeURIComponent(q)}`),
  campaigns: () => request<Item[]>("GET", "/campaigns"),
  campaign: (id: number) => request<CampaignView>("GET", `/campaigns/${id}`),
  fetchCampaign: (id: number) => request<CampaignView>("POST", `/campaigns/${id}/fetch`),
  createCampaign: (body: CreateCampaign) => request<CampaignView>("POST", "/campaigns", body),

  addOffer: (streamId: number, offerId: number) =>
    request<StreamView>("POST", `${streamPath(streamId)}/offers`, { offer_id: offerId }),
  removeOffer: (streamId: number, offerId: number) =>
    request<StreamView>("DELETE", streamPath(streamId, offerId)),
  restoreOffer: (streamId: number, offerId: number) =>
    request<StreamView>("POST", `${streamPath(streamId, offerId)}/restore`),
  pin: (streamId: number, offerId: number, share: number) =>
    request<StreamView>("PUT", `${streamPath(streamId, offerId)}/pin`, { share }),
  unpin: (streamId: number, offerId: number) =>
    request<StreamView>("DELETE", `${streamPath(streamId, offerId)}/pin`),
  push: (streamId: number) => request<StreamView>("POST", `${streamPath(streamId)}/push`),
  cancel: (streamId: number) => request<StreamView>("POST", `${streamPath(streamId)}/cancel`),
};
