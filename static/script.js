document.addEventListener('DOMContentLoaded', () => {
    const youtubeUrlInput = document.getElementById('youtubeUrl');
    const clearBtn = document.getElementById('clearBtn');
    const fetchBtn = document.getElementById('fetchBtn');
    const errorAlert = document.getElementById('errorAlert');
    const errorMessage = document.getElementById('errorMessage');
    const loadingState = document.getElementById('loadingState');
    
    const videoCard = document.getElementById('videoCard');
    const videoThumbnail = document.getElementById('videoThumbnail');
    const videoDuration = document.getElementById('videoDuration');
    const videoTitle = document.getElementById('videoTitle');
    const videoChannel = document.getElementById('videoChannel');
    const videoViews = document.getElementById('videoViews');
    
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    const videoQualitySelect = document.getElementById('videoQualitySelect');
    const audioFormatSelect = document.getElementById('audioFormatSelect');
    const downloadBtn = document.getElementById('downloadBtn');

    const progressCard = document.getElementById('progressCard');
    const progressStatusText = document.getElementById('progressStatusText');
    const progressPercent = document.getElementById('progressPercent');
    const progressBarFill = document.getElementById('progressBarFill');
    const downloadSpeed = document.getElementById('downloadSpeed');
    const downloadEta = document.getElementById('downloadEta');
    const completedActions = document.getElementById('completedActions');
    const saveFileBtn = document.getElementById('saveFileBtn');

    let activeTab = 'videoTab';
    let currentVideoUrl = '';
    let pollingInterval = null;

    // Mode Switcher (YouTube vs Any Site URL)
    const modeBtns = document.querySelectorAll('.mode-btn');
    let currentMode = 'youtube';

    modeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            modeBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentMode = btn.getAttribute('data-mode');

            if (currentMode === 'youtube') {
                youtubeUrlInput.placeholder = 'Paste YouTube link here... (e.g. https://www.youtube.com/watch?v=...)';
            } else {
                youtubeUrlInput.placeholder = 'Paste any video URL here... (Facebook, Instagram, TikTok, Twitter, Vimeo, etc.)';
            }
            youtubeUrlInput.focus();
        });
    });

    // Clear input
    clearBtn.addEventListener('click', () => {
        youtubeUrlInput.value = '';
        resetUI();
    });

    // Handle Tab switching
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.add('hidden'));

            btn.classList.add('active');
            activeTab = btn.getAttribute('data-tab');
            document.getElementById(activeTab).classList.remove('hidden');
        });
    });

    // Fetch video info
    fetchBtn.addEventListener('click', handleFetchInfo);
    youtubeUrlInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            handleFetchInfo();
        }
    });

    async function handleFetchInfo() {
        const url = youtubeUrlInput.value.trim();
        if (!url) {
            showError('Please paste a valid YouTube video link.');
            return;
        }

        resetUI();
        hideError();
        loadingState.classList.remove('hidden');

        try {
            const response = await fetch('/api/info', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url })
            });

            const data = await response.json();

            if (!response.ok || data.error) {
                throw new Error(data.error || 'Failed to fetch video details.');
            }

            currentVideoUrl = data.url;
            displayVideoData(data);
        } catch (err) {
            showError(err.message);
        } finally {
            loadingState.classList.add('hidden');
        }
    }

    function displayVideoData(data) {
        videoThumbnail.src = data.thumbnail || '';
        videoDuration.textContent = data.duration || '00:00';
        videoTitle.textContent = data.title || 'YouTube Video';
        videoChannel.textContent = data.channel || 'Unknown Uploader';
        videoViews.textContent = `${data.views} views`;

        // Populate Video Quality dropdown
        videoQualitySelect.innerHTML = '';
        if (data.video_options && data.video_options.length > 0) {
            data.video_options.forEach(opt => {
                const option = document.createElement('option');
                option.value = opt.resolution;
                option.textContent = opt.label || `${opt.resolution} - ${opt.size}`;
                videoQualitySelect.appendChild(option);
            });
        } else {
            const option = document.createElement('option');
            option.value = 'best';
            option.textContent = 'Best Available Quality';
            videoQualitySelect.appendChild(option);
        }

        videoCard.classList.remove('hidden');
    }

    // Start Download trigger
    downloadBtn.addEventListener('click', async () => {
        if (!currentVideoUrl) return;

        const isAudio = activeTab === 'audioTab';
        const formatType = isAudio ? 'audio' : 'video';
        const selectedQuality = isAudio 
            ? audioFormatSelect.value 
            : (videoQualitySelect.value || 'best');

        progressCard.classList.remove('hidden');
        completedActions.classList.add('hidden');
        progressBarFill.style.width = '0%';
        progressPercent.textContent = '0%';
        progressStatusText.innerHTML = `<i class="fa-solid fa-cloud-arrow-down spin"></i> Initializing download...`;
        downloadBtn.disabled = true;

        try {
            const response = await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url: currentVideoUrl,
                    format_type: formatType,
                    quality: selectedQuality
                })
            });

            const data = await response.json();
            if (!response.ok || data.error) {
                throw new Error(data.error || 'Could not start download.');
            }

            // Start polling progress
            startPolling(data.task_id);
        } catch (err) {
            showError(err.message);
            downloadBtn.disabled = false;
            progressCard.classList.add('hidden');
        }
    });

    function startPolling(taskId) {
        if (pollingInterval) clearInterval(pollingInterval);

        pollingInterval = setInterval(async () => {
            try {
                const res = await fetch(`/api/progress/${taskId}`);
                const task = await res.json();

                if (!res.ok || task.error) {
                    clearInterval(pollingInterval);
                    showError(task.error || 'Download failed.');
                    downloadBtn.disabled = false;
                    return;
                }

                if (task.status === 'downloading') {
                    const rawProgress = task.progress || '0%';
                    progressBarFill.style.width = rawProgress;
                    progressPercent.textContent = rawProgress;
                    downloadSpeed.textContent = task.speed || '0 B/s';
                    downloadEta.textContent = task.eta || 'Calculating...';
                    progressStatusText.innerHTML = `<i class="fa-solid fa-cloud-arrow-down spin"></i> Downloading...`;
                } else if (task.status === 'processing') {
                    progressBarFill.style.width = '100%';
                    progressPercent.textContent = '100%';
                    progressStatusText.innerHTML = `<i class="fa-solid fa-gear spin"></i> Processing & converting file...`;
                } else if (task.status === 'completed') {
                    clearInterval(pollingInterval);
                    progressBarFill.style.width = '100%';
                    progressPercent.textContent = '100%';
                    progressStatusText.innerHTML = `<i class="fa-solid fa-check"></i> Finished!`;
                    downloadSpeed.textContent = 'Complete';
                    downloadEta.textContent = '0s';

                    saveFileBtn.href = task.download_url;
                    completedActions.classList.remove('hidden');
                    downloadBtn.disabled = false;
                } else if (task.status === 'failed') {
                    clearInterval(pollingInterval);
                    showError(task.error || 'Download failed during extraction.');
                    downloadBtn.disabled = false;
                }
            } catch (err) {
                console.error(err);
            }
        }, 1000);
    }

    function showError(msg) {
        errorMessage.textContent = msg;
        errorAlert.classList.remove('hidden');
    }

    function hideError() {
        errorAlert.classList.add('hidden');
    }

    function resetUI() {
        hideError();
        videoCard.classList.add('hidden');
        progressCard.classList.add('hidden');
        completedActions.classList.add('hidden');
        if (pollingInterval) clearInterval(pollingInterval);
        downloadBtn.disabled = false;
    }
});
