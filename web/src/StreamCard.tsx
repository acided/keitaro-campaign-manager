import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type CampaignView, type Item, type OfferView, type StreamView } from "./api";
import { OfferPicker } from "./OfferPicker";

/** One stream. White = as in Keitaro, yellow = unpublished draft, grey rows = removed offers. */
export function StreamCard({ campaignId, stream }: { campaignId: number; stream: StreamView }) {
  const queryClient = useQueryClient();
  const [newOffer, setNewOffer] = useState<Item | null>(null);

  // Every action returns the whole stream: put it into the cached campaign and re-render.
  const action = useMutation({
    mutationFn: (run: () => Promise<StreamView>) => run(),
    onSuccess: (updated) => {
      queryClient.setQueryData<CampaignView>(["campaign", campaignId], (campaign) =>
        campaign && {
          ...campaign,
          streams: campaign.streams.map((s) => (s.id === updated.id ? updated : s)),
        },
      );
      setNewOffer(null);
    },
  });
  const run = (call: () => Promise<StreamView>) => action.mutate(call);

  if (!stream.has_offers) {
    return (
      <section className="card stream">
        <h3>
          {stream.position}. {stream.name}
        </h3>
        <p className="muted">Stream without offers.</p>
      </section>
    );
  }

  return (
    <section className={`card stream ${stream.dirty ? "dirty" : ""}`}>
      <h3>
        {stream.position}. {stream.name}
        {stream.dirty && <span className="badge">unpublished</span>}
      </h3>

      <table>
        <thead>
          <tr>
            <th>Offer</th>
            <th className="num">Share</th>
            <th>Pin</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {stream.offers.map((offer) => (
            <OfferRow
              key={offer.offer_id}
              offer={offer}
              busy={action.isPending}
              onRemove={() => run(() => api.removeOffer(stream.id, offer.offer_id))}
              onRestore={() => run(() => api.restoreOffer(stream.id, offer.offer_id))}
              onPin={(share) => run(() => api.pin(stream.id, offer.offer_id, share))}
              onUnpin={() => run(() => api.unpin(stream.id, offer.offer_id))}
            />
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td>Total</td>
            <td className={`num ${stream.total_share === 100 ? "" : "error"}`}>{stream.total_share}%</td>
            <td colSpan={2} />
          </tr>
        </tfoot>
      </table>

      <div className="row">
        <OfferPicker value={newOffer} onChange={setNewOffer} />
        <button
          disabled={!newOffer || action.isPending}
          onClick={() => newOffer && run(() => api.addOffer(stream.id, newOffer.id))}
        >
          Add
        </button>
      </div>

      {stream.dirty && stream.push_blocked_reason && <p className="error">{stream.push_blocked_reason}</p>}
      {action.error && <p className="error">{action.error.message}</p>}

      <div className="row actions">
        <button
          className="primary"
          disabled={!stream.dirty || !!stream.push_blocked_reason || action.isPending}
          onClick={() => run(() => api.push(stream.id))}
        >
          Push
        </button>
        <button disabled={!stream.dirty || action.isPending} onClick={() => run(() => api.cancel(stream.id))}>
          Cancel
        </button>
      </div>
    </section>
  );
}

function OfferRow({
  offer,
  busy,
  onRemove,
  onRestore,
  onPin,
  onUnpin,
}: {
  offer: OfferView;
  busy: boolean;
  onRemove: () => void;
  onRestore: () => void;
  onPin: (share: number) => void;
  onUnpin: () => void;
}) {
  // null = follow the current share; a string = what the user is typing
  const [typed, setTyped] = useState<string | null>(null);
  const pinValue = typed ?? String(offer.share);
  const removed = offer.state === "removed";

  return (
    <tr className={removed ? "removed" : ""}>
      <td>
        {offer.name}
        {offer.change && <span className={`change ${offer.change}`}>{offer.change}</span>}
      </td>
      <td className="num">{offer.share}%</td>
      <td>
        {offer.pin !== null ? (
          <>
            📌 {offer.pin}%{" "}
            <button className="link" disabled={busy} onClick={onUnpin}>
              Unpin
            </button>
          </>
        ) : (
          !removed && (
            <>
              <input
                className="share"
                type="number"
                min={0}
                max={100}
                value={pinValue}
                onChange={(e) => setTyped(e.target.value)}
              />
              <button
                className="link"
                disabled={busy || pinValue === ""}
                onClick={() => {
                  onPin(Number(pinValue));
                  setTyped(null);
                }}
              >
                Pin
              </button>
            </>
          )
        )}
      </td>
      <td className="num">
        {removed ? (
          <button disabled={busy} onClick={onRestore}>
            Bring back
          </button>
        ) : (
          <button disabled={busy} onClick={onRemove}>
            Remove
          </button>
        )}
      </td>
    </tr>
  );
}
