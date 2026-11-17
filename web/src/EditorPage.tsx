import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type CampaignView } from "./api";
import { openCampaign } from "./App";
import { StreamCard } from "./StreamCard";

export function EditorPage({ campaignId }: { campaignId: number | null }) {
  const queryClient = useQueryClient();
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: api.campaigns });
  const campaign = useQuery({
    queryKey: ["campaign", campaignId],
    queryFn: () => api.campaign(campaignId!),
    enabled: campaignId !== null,
  });
  const fetchStreams = useMutation({
    mutationFn: () => api.fetchCampaign(campaignId!),
    onSuccess: (view) => queryClient.setQueryData<CampaignView>(["campaign", campaignId], view),
  });

  // 404 = we have never fetched this campaign, not an error for the user
  const notFetched = campaign.error instanceof ApiError && campaign.error.status === 404;

  return (
    <>
      <div className="card toolbar">
        <select
          value={campaignId ?? ""}
          onChange={(e) => openCampaign(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">
            {campaigns.isLoading ? "Loading campaigns…" : "Choose a campaign"}
          </option>
          {campaigns.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} (#{c.id})
            </option>
          ))}
        </select>
        <button
          disabled={campaignId === null || fetchStreams.isPending}
          onClick={() => fetchStreams.mutate()}
        >
          {fetchStreams.isPending ? "Fetching…" : "Fetch streams"}
        </button>
        {campaigns.error && <span className="error">{campaigns.error.message}</span>}
        {fetchStreams.error && <span className="error">{fetchStreams.error.message}</span>}
      </div>

      {notFetched && <p className="muted">Press “Fetch streams” to load this campaign from Keitaro.</p>}
      {campaign.error && !notFetched && <p className="error">{campaign.error.message}</p>}
      {campaign.data?.streams.map((stream) => (
        <StreamCard key={stream.id} campaignId={campaign.data.id} stream={stream} />
      ))}
    </>
  );
}
