import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, type Item } from "./api";
import { openCampaign } from "./App";
import { OfferPicker } from "./OfferPicker";

function Select({
  label,
  items,
  value,
  onChange,
}: {
  label: string;
  items: Item[];
  value: number | null;
  onChange: (id: number) => void;
}) {
  return (
    <label>
      {label}
      <select value={value ?? ""} onChange={(e) => onChange(Number(e.target.value))}>
        {items.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </select>
    </label>
  );
}

export function CreatePage() {
  const queryClient = useQueryClient();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const [name, setName] = useState("");
  const [geo, setGeo] = useState("");
  const [offer, setOffer] = useState<Item | null>(null);
  // null = use the default from /api/meta
  const [domainId, setDomainId] = useState<number | null>(null);
  const [groupId, setGroupId] = useState<number | null>(null);
  const [sourceId, setSourceId] = useState<number | null>(null);

  const domain = domainId ?? meta.data?.default_domain_id ?? null;
  const group = groupId ?? meta.data?.default_group_id ?? null;
  const source = sourceId ?? meta.data?.default_traffic_source_id ?? null;

  const create = useMutation({
    mutationFn: api.createCampaign,
    onSuccess: (campaign) => {
      queryClient.setQueryData(["campaign", campaign.id], campaign);
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      openCampaign(campaign.id);
    },
  });

  const ready = name.trim() && geo.trim() && offer && domain && group && source;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    create.mutate({
      name,
      geo,
      offer_id: offer.id,
      domain_id: domain,
      group_id: group,
      traffic_source_id: source,
    });
  }

  return (
    <form className="card create" onSubmit={submit}>
      <h2>New campaign</h2>
      <label>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="my_campaign" />
        <small>The test_kochkurov_ prefix is added automatically.</small>
      </label>
      <label>
        Geo
        <input value={geo} onChange={(e) => setGeo(e.target.value)} placeholder="MX,AU,RO" />
        <small>Stream 1 sends these countries to google.com, stream 2 sends everyone else to the offer.</small>
      </label>
      <label>
        Offer
        <OfferPicker value={offer} onChange={setOffer} />
      </label>

      {meta.error && <p className="error">Cannot load domains and groups: {meta.error.message}</p>}
      {meta.data && (
        <div className="row">
          <Select label="Domain" items={meta.data.domains} value={domain} onChange={setDomainId} />
          <Select label="Group" items={meta.data.groups} value={group} onChange={setGroupId} />
          <Select
            label="Traffic source"
            items={meta.data.traffic_sources}
            value={source}
            onChange={setSourceId}
          />
        </div>
      )}

      {create.error && <p className="error">{create.error.message}</p>}
      <button type="submit" disabled={!ready || create.isPending}>
        {create.isPending ? "Creating…" : "Create"}
      </button>
    </form>
  );
}
