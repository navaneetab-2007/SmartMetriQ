document.addEventListener('DOMContentLoaded', () => {
  const startCameraBtn = document.getElementById('startCameraBtn');
  const captureBtn = document.getElementById('captureBtn');
  const retakeBtn = document.getElementById('retakeBtn');
  const submitBtn = document.getElementById('submitBtn');
  const imageUpload = document.getElementById('imageUpload');
  const imageTypeSelect = document.getElementById('imageType');
  const languageSelect = document.getElementById('languageSelect');
  const imagePreview = document.getElementById('imagePreview');
  const imagePreviewContainer = document.getElementById('imagePreviewContainer');
  const cameraStream = document.getElementById('cameraStream');
  const cameraPlaceholder = document.getElementById('cameraPlaceholder');
  const capturedCanvas = document.getElementById('capturedCanvas');

  let stream = null;
  let capturedImageData = null;
  let selectedFile = null;

  function showPreviewFromDataUrl(dataUrl, fromCamera = false) {
    imagePreview.src = dataUrl;
    imagePreviewContainer.hidden = false;

    if (fromCamera) {
      capturedImageData = dataUrl;
      selectedFile = null;
      imageUpload.value = ''; // clear any previously selected file
    }
  }

  async function startCamera() {
    if (!navigator.mediaDevices?.getUserMedia) {
      alert('Camera API is not supported in this browser.');
      return;
    }

    try {
      // Stop any existing stream before starting a new one
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
      }

      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
        audio: false
      });

      cameraStream.srcObject = stream;
      cameraPlaceholder.hidden = true;
      captureBtn.disabled = false;
      startCameraBtn.textContent = 'Camera Ready';
      startCameraBtn.disabled = true;
    } catch (error) {
      alert('Camera access was denied or is unavailable. Please allow camera permission or upload an image instead.');
      console.error('Camera error:', error);
    }
  }

  function captureImage() {
    if (!stream) {
      alert('Start the camera before capturing an image.');
      return;
    }

    const context = capturedCanvas.getContext('2d');
    const width = cameraStream.videoWidth || 640;
    const height = cameraStream.videoHeight || 480;

    capturedCanvas.width = width;
    capturedCanvas.height = height;
    context.drawImage(cameraStream, 0, 0, width, height);

    const dataUrl = capturedCanvas.toDataURL('image/png');
    showPreviewFromDataUrl(dataUrl, true);
    retakeBtn.hidden = false;
  }

  function retakeImage() {
    imagePreviewContainer.hidden = true;
    capturedImageData = null;
    selectedFile = null;
    retakeBtn.hidden = true;
    imagePreview.src = '';
    imageUpload.value = ''; // clear file input so it doesn't submit old file
  }

  imageUpload.addEventListener('change', (event) => {
    const file = event.target.files[0];

    if (!file) {
      return;
    }

    const validTypes = ['image/jpeg', 'image/png', 'image/jpg'];
    if (!validTypes.includes(file.type)) {
      alert('Only JPG, JPEG, and PNG files are allowed.');
      imageUpload.value = '';
      return;
    }

    selectedFile = file;
    capturedImageData = null; // upload takes precedence over camera capture

    const reader = new FileReader();
    reader.onload = (e) => {
      imagePreview.src = e.target.result;
      imagePreviewContainer.hidden = false;
      retakeBtn.hidden = false;
    };
    reader.readAsDataURL(file);
  });

  async function submitImageForAnalysis() {
    if (!capturedImageData && !selectedFile && !imageUpload.files.length) {
      alert('Please capture or upload an image before submitting.');
      return;
    }

    const formData = new FormData();
    const imageType = imageTypeSelect.value;
    const language = languageSelect.value;
    formData.append('image_type', imageType);
    formData.append('language', language);

    if (selectedFile) {
      formData.append('image', selectedFile);
    } else if (capturedImageData) {
      const blob = await fetch(capturedImageData).then((response) => response.blob());
      formData.append('image', blob, 'captured-image.png');
    } else {
      formData.append('image', imageUpload.files[0]);
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Analyzing...';

    try {
      const response = await fetch('/upload', {
        method: 'POST',
        body: formData
      });

      let result;
      try {
        result = await response.json();
      } catch (error) {
        throw new Error('The server did not return a valid analysis response.');
      }

      if (!response.ok || !result.success) {
        throw new Error(result.message || 'Analysis could not be completed. Please try again.');
      }

      if (result.redirect_url) {
        window.location.href = result.redirect_url;
        return;
      }

      throw new Error('No analysis page was returned by the server.');
    } catch (error) {
      alert(error.message || 'Analysis could not be completed. Please try again.');
      console.error('Upload error:', error);
      submitBtn.disabled = false;
      submitBtn.textContent = 'Submit for Analysis';
    }
  }

  submitBtn.addEventListener('click', submitImageForAnalysis);
  startCameraBtn.addEventListener('click', startCamera);
  captureBtn.addEventListener('click', captureImage);
  retakeBtn.addEventListener('click', retakeImage);
});
