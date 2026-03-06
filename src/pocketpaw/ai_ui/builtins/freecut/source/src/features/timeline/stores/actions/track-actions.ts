/**
 * Track Actions - Operations on timeline tracks.
 */

import type { TimelineTrack } from '@/types/timeline';
import { useItemsStore } from '../items-store';
import { useTimelineSettingsStore } from '../timeline-settings-store';
import { execute } from './shared';
import { DEFAULT_TRACK_HEIGHT } from '../../constants';

export function setTracks(tracks: TimelineTrack[]): void {
  execute('SET_TRACKS', () => {
    useItemsStore.getState().setTracks(tracks);
    useTimelineSettingsStore.getState().markDirty();
  }, { count: tracks.length });
}

/**
 * Create a group track from selected tracks.
 * Inserts a new group track at the position of the first selected track,
 * and parents all selected tracks under it.
 */
export function createGroup(trackIds: string[]): void {
  if (trackIds.length === 0) return;

  execute('CREATE_GROUP', () => {
    const tracks = useItemsStore.getState().tracks;

    // Don't allow grouping tracks that are already group containers
    const selectedTracks = tracks.filter((t) => trackIds.includes(t.id));
    if (selectedTracks.some((t) => t.isGroup)) return;

    // Don't allow grouping tracks from different parent groups
    const parentIds = new Set(selectedTracks.map((t) => t.parentTrackId ?? null));
    if (parentIds.size > 1) return;

    // Find the index of the first selected track (by order)
    const sortedSelected = [...selectedTracks].sort((a, b) => a.order - b.order);
    const firstSelected = sortedSelected[0];
    if (!firstSelected) return;

    // Find the insertion position — just before the first selected track
    const firstIndex = tracks.findIndex((t) => t.id === firstSelected.id);
    const orderBefore = firstIndex > 0 ? (tracks[firstIndex - 1]?.order ?? firstSelected.order - 2) : firstSelected.order - 2;
    const groupOrder = (orderBefore + firstSelected.order) / 2;

    // Create the group track
    const groupTrack: TimelineTrack = {
      id: `group-${Date.now()}`,
      name: `Group`,
      height: DEFAULT_TRACK_HEIGHT,
      locked: false,
      visible: true,
      muted: false,
      solo: false,
      order: groupOrder,
      items: [],
      isGroup: true,
      isCollapsed: false,
      parentTrackId: firstSelected.parentTrackId, // inherit parent if grouping within a group
    };

    // Reparent selected tracks under the new group
    const selectedIds = new Set(trackIds);
    const updatedTracks = tracks.map((t) => {
      if (selectedIds.has(t.id)) {
        return { ...t, parentTrackId: groupTrack.id };
      }
      return t;
    });

    // Insert group track and re-sort
    const newTracks = [groupTrack, ...updatedTracks].sort((a, b) => a.order - b.order);

    useItemsStore.getState().setTracks(newTracks);
    useTimelineSettingsStore.getState().markDirty();
  }, { trackIds });
}

/**
 * Dissolve a group, promoting its children to top-level (or parent group).
 */
export function ungroup(groupTrackId: string): void {
  execute('UNGROUP', () => {
    const tracks = useItemsStore.getState().tracks;
    const groupTrack = tracks.find((t) => t.id === groupTrackId);
    if (!groupTrack?.isGroup) return;

    // Promote children to the group's parent (or top-level)
    const updatedTracks = tracks
      .filter((t) => t.id !== groupTrackId) // Remove the group track
      .map((t) => {
        if (t.parentTrackId === groupTrackId) {
          return { ...t, parentTrackId: groupTrack.parentTrackId };
        }
        return t;
      });

    useItemsStore.getState().setTracks(updatedTracks);
    useTimelineSettingsStore.getState().markDirty();
  }, { groupTrackId });
}

/**
 * Toggle the collapsed state of a group track.
 */
export function toggleGroupCollapse(groupTrackId: string): void {
  execute('TOGGLE_GROUP_COLLAPSE', () => {
    const tracks = useItemsStore.getState().tracks;
    const updatedTracks = tracks.map((t) => {
      if (t.id === groupTrackId && t.isGroup) {
        return { ...t, isCollapsed: !t.isCollapsed };
      }
      return t;
    });

    useItemsStore.getState().setTracks(updatedTracks);
    useTimelineSettingsStore.getState().markDirty();
  }, { groupTrackId });
}

/**
 * Move tracks into an existing group.
 */
export function addToGroup(trackIds: string[], groupTrackId: string): void {
  if (trackIds.length === 0) return;

  execute('ADD_TO_GROUP', () => {
    const tracks = useItemsStore.getState().tracks;
    const groupTrack = tracks.find((t) => t.id === groupTrackId);
    if (!groupTrack?.isGroup) return;

    const selectedIds = new Set(trackIds);
    const updatedTracks = tracks.map((t) => {
      if (selectedIds.has(t.id) && !t.isGroup) {
        return { ...t, parentTrackId: groupTrackId };
      }
      return t;
    });

    useItemsStore.getState().setTracks(updatedTracks);
    useTimelineSettingsStore.getState().markDirty();
  }, { trackIds, groupTrackId });
}

/**
 * Remove tracks from their group (detach to top-level or parent's parent).
 */
export function removeFromGroup(trackIds: string[]): void {
  if (trackIds.length === 0) return;

  execute('REMOVE_FROM_GROUP', () => {
    const tracks = useItemsStore.getState().tracks;
    const selectedIds = new Set(trackIds);

    const updatedTracks = tracks.map((t) => {
      if (selectedIds.has(t.id) && t.parentTrackId) {
        // Find the group's parent to promote to
        const group = tracks.find((g) => g.id === t.parentTrackId);
        return { ...t, parentTrackId: group?.parentTrackId };
      }
      return t;
    });

    useItemsStore.getState().setTracks(updatedTracks);
    useTimelineSettingsStore.getState().markDirty();
  }, { trackIds });
}
