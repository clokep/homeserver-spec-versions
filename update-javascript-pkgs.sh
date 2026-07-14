echo "Refreshing chart.js"
curl --no-progress-meter https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js > lib/chart.umd.min.js

echo "Refreshing chart.js adapter: date-fns"
curl --no-progress-meter https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js > lib/chartjs-adapter-date-fns.bundle.min.js

echo "Refreshing chart.js plugin: annotation"
curl --no-progress-meter https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.1.0/dist/chartjs-plugin-annotation.min.js > lib/chartjs-plugin-annotation.min.js

echo "Refreshing chart.js plugin: datalabels"
curl --no-progress-meter https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js > lib/chartjs-plugin-datalabels.min.js

echo "Refreshing chart.js plugin: zoom"
curl --no-progress-meter https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.2.0/dist/chartjs-plugin-zoom.min.js > lib/chartjs-plugin-zoom.min.js

echo "Refreshing hammer.js"
curl --no-progress-meter https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js > lib/hammer.min.js
