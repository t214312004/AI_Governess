# Voice Profiles

請在這裡建立英文資料夾名稱的說話者 profile，例如：

- `voice_profiles/ViVi/sample_01.wav`
- `voice_profiles/ViVi/sample_02.wav`
- `voice_profiles/Troy/sample_01.wav`

系統會把資料夾名稱視為說話者名稱，並會在檔案變動後自動重載 profiles。

建議做法：

- 從 `whisper_audio_archive/` 挑出代表性的 `.wav`
- 複製到對應的英文資料夾中
- 每位家人先放 1 到 3 個樣本即可，單檔建議至少超過 0.8 秒
- 若你放入多個 `.wav`，系統會先為同一位家人的樣本做平均後再比對
