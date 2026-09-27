# Output switching

In All system audio mode, choose **Follow Windows default output** to follow
the Windows multimedia playback endpoint. A meeting app pinned to another
output needs that fixed output selected instead. Changes are checked every
750 milliseconds. Device initialization adds reconnection time.

The System Audio dropdown remains available during recording and pause when
recording started with an output selected. Choosing another output reconnects
only the system stream. Choosing None stops system capture but leaves the dropdown
available to select an output again. Starting with no system audio selected keeps
the dropdown disabled for that recording. Microphone settings remain fixed.
Device unavailability is shown in the status bar and retried. If a stream receives
no packets for ten seconds, the status asks the user to check playback/output.
Silence alone is not proof of a disconnected device.

System audio keeps a continuous, pause-aware timeline. Packet gaps and reconnect
gaps become silence; speech lost while an endpoint reconnects cannot be recovered.
Fixed-output matching fails visibly instead of selecting a different output.
Capture timestamps, calibrated to the monotonic clock before a stream starts,
keep buffered packets in position when callbacks arrive late. Overlapping data
is trimmed when clock differences exceed 50 milliseconds. Timing reference:
https://www.portaudio.com/docs/v19-doxydocs/structPaStreamCallbackTimeInfo.html

Follow-default can discover a newly connected Windows output during recording.
The manual dropdown lists devices discovered while idle; a newly connected device
may require returning to idle before it can be selected by name.

Acceptance: speakers to headphones to speakers in one recording, pause/resume,
and disconnect/reconnect. Verify both voices and timestamps in the exported full
transcript. Hardware checks must distinguish wired devices from Bluetooth profiles.
