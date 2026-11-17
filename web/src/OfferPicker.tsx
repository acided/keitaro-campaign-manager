import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type Item } from "./api";

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

/** Offer autocomplete: search by id or name, pick one from the list. */
export function OfferPicker({
  value,
  onChange,
}: {
  value: Item | null;
  onChange: (offer: Item | null) => void;
}) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const query = useDebounced(text.trim(), 250);
  const offers = useQuery({
    queryKey: ["offers", query],
    queryFn: () => api.searchOffers(query),
    enabled: open && query.length > 0,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (value === null) setText("");
  }, [value]);

  return (
    <div className="picker">
      <input
        placeholder="Search offer by id or name"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
          onChange(null);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && query && (
        <ul>
          {offers.isLoading && <li className="muted">Searching…</li>}
          {offers.error && <li className="error">{offers.error.message}</li>}
          {offers.data?.length === 0 && <li className="muted">No active offers found</li>}
          {offers.data?.map((offer) => (
            <li
              key={offer.id}
              onMouseDown={() => {
                onChange(offer);
                setText(offer.name);
                setOpen(false);
              }}
            >
              {offer.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
