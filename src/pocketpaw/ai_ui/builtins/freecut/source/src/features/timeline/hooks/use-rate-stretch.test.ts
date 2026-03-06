import { describe, expect, it } from 'vitest';
import { MAX_SPEED, timelineToSourceFrames } from '../utils/source-calculations';
import { getDurationLimits, getClampedSpeed, resolveDurationAndSpeed } from './use-rate-stretch';

describe('use-rate-stretch regression', () => {
  it('uses a ceil-based min duration so max-speed stretch does not drop source frames', () => {
    const sourceDuration = 100;
    const sourceFps = 30;
    const timelineFps = 30;

    const limits = getDurationLimits(sourceDuration, false, sourceFps, timelineFps);
    expect(limits.min).toBe(7); // ceil(100 / 16)

    const speedAtMin = getClampedSpeed(sourceDuration, limits.min, sourceFps, timelineFps);
    expect(speedAtMin).toBeLessThanOrEqual(MAX_SPEED);

    const coveredSourceFrames = timelineToSourceFrames(limits.min, speedAtMin, timelineFps, sourceFps);
    expect(coveredSourceFrames).toBeGreaterThanOrEqual(sourceDuration);
  });

  it('normalizes over-fast proposals to avoid accidental source-span trim', () => {
    const sourceDuration = 100;
    const sourceFps = 30;
    const timelineFps = 30;

    // Proposed duration is too short to cover full source at MAX_SPEED.
    const resolved = resolveDurationAndSpeed(sourceDuration, 6, sourceFps, timelineFps);
    expect(resolved.duration).toBeGreaterThanOrEqual(7);
    expect(resolved.speed).toBeLessThanOrEqual(MAX_SPEED);

    const coveredSourceFrames = timelineToSourceFrames(
      resolved.duration,
      resolved.speed,
      timelineFps,
      sourceFps
    );
    expect(coveredSourceFrames).toBeGreaterThanOrEqual(sourceDuration);
  });
});
