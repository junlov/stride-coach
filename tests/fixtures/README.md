# Synthetic run detail fixtures

All coordinates, times, metrics and devices are invented. JSON follows the Garmin activity,
laps, hrTimeInZones and descriptor-indexed details shapes consumed by the pinned client.
`synthetic-run.fit` is an 84-byte synthetic FIT activity with a file_id message and six record
messages (timestamp, heart rate, cadence), using FIT CRC-16. It is not a real recording.
The FIT and JSON fixtures exercise separate archive and normalization paths; JSON includes
extra invented channels to cover sensors absent from the minimal FIT.
