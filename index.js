const zoomOptions = {
    pan: {
        enabled: true,
        modifierKey: "shift",
    },
    zoom: {
        pinch: {
            enabled: true,
        },
        drag: {
            enabled: true,
        },
        mode: 'xy',
    }
};

function cmpVersions(a, b) {
    // Build an array of the first character, then the partial version numbers.
    let A = [a[0]];
    A.push( ...a.split(".").map(Number));

    let B = [b[0]];
    B.push( ...b.split(".").map(Number));

    for (let i = 0; i < a.length; ++i) {
        // If B[i] is undefined, A must be earlier.
        if (B[i] === undefined) {
            return -1
        }

        // Otherwise compare the individual items.
        if (A[i] < B[i]) {
            return -1;
        } else if (A[i] > B[i]) {
            return 1;
        }

    }
}

function cmpRoomVersions(a, b) {
    return Number(a) - Number(b);
}

function resetZoom(chartId) {
    Chart.getChart(chartId).resetZoom();
}

/**
 * Add a data point to a bar graph.
 */
function addVersionsToDataset(dataset, now, project, projectVersions) {
    // If there are no versions, don't bother adding them.
    if (!Object.keys(projectVersions).length) {
        return
    }

    dataset.push(
        {
            label: project,
            // Convert the mapping of version -> list of dates to a flat
            // array of objects with y value of the version and x the start
            // & end date of that version.
            data: Object.keys(projectVersions).map(
                verString => projectVersions[verString].map(
                    verDates => {
                        return {
                            x: [verDates[0], verDates[1] || now],
                            y: verString
                        };
                    }
                )
            ).flat(),
        }
    );
}

function buildTimeline(elementId, title, yAxisTitle, earliestDate) {
    const context = document.getElementById(elementId);
    new Chart(context, {
        type: "bar",
        data: null,
        options: {
            // Add height since there's so many lines.
            aspectRatio: 1,
            // Horizontal bars.
            indexAxis: "y",
            plugins: {
                title: {
                    display: true,
                    text: title,
                },
                zoom: zoomOptions
            },
            scales: {
                x: {
                    min: earliestDate,
                    title: {
                        display: true,
                        text: "Date"
                    },
                    type: "time"
                },
                y: {
                    title: {
                        display: true,
                        text: yAxisTitle
                    }
                }
            }
        },
    });
}

function build() {
    // Bar chart of the number of days between a spec release and the homeserver
    // supporting it.
    const barContext = document.getElementById("days-to-support");
    new Chart(barContext, {
        type: "bar",
        data: null,
        options: {
            plugins: {
                title: {
                    display: true,
                    text: "Days to support spec version",
                },
                zoom: zoomOptions,
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: "Spec version"
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: "Days to support"
                    }
                }
            }
        }
    });

    // Scatter chart of the number of days between a spec release and the homeserver
    // supporting it.
    const scatterContext = document.getElementById("spec-days-vs-support");
    new Chart(scatterContext, {
        type: "scatter",
        data: null,
        options: {
            plugins: {
                datalabels: {
                    align: "end"
                },
                title: {
                    display: true,
                    text: "Spec days vs. support days",
                },
                zoom: zoomOptions
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: "Days since last spec"
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: "Days to support"
                    }
                }
            }
        },
        plugins: [ChartDataLabels]
    });

    // Timeline of supported versions.
    buildTimeline("supported-spec-versions-over-time", "Supported spec versions over time", "Spec version", "2015-10-01");
    buildTimeline("supported-room-versions-over-time", "Supported room versions over time", "Room version", "2015-10-01");
    buildTimeline("default-room-versions-over-time", "Default room versions over time", "Room version", "2015-10-01");

    // Add the initial data.
    render();
}

function annotationsFromReleaseDates(releaseDates, rotation) {
    return Object.entries(releaseDates).map(
        ([specVersion, releaseDate]) => {
            return {
                id: specVersion,
                type: "line",
                xMin: releaseDate,
                xMax: releaseDate,
                yMax: specVersion,
                borderWidth: 1,
                borderDash: [10, 10],
                label: {
                    display: true,
                    content: specVersion,
                    rotation: rotation,
                    position: "center"
                }
            }
        }
    );
}

function render() {
    let allowedMaturities = ["stable", "beta", "alpha", "obsolete", "unstarted"].filter(maturity => document.getElementById(maturity).checked);
    let displayType = document.getElementById("display-type").value;

    fetch("data.json").then(response => response.json()).then(data => {
        // Filter the displayed projects by maturity.
        data.homeserver_versions = Object.fromEntries(
            Object.entries(data.homeserver_versions).filter(
                ([project, projectInfo]) => allowedMaturities.includes(projectInfo.maturity)
            )
        );

        renderData(data, displayType);
    });
}

/**
 * Render the data which has already been filtered for ignored homeservers.
 */
function renderData(data, displayType) {
    // The full list of released spec versions.
    const specVersions = Object.keys(data.spec_versions.version_dates).sort(cmpVersions);
    // The full list of room versions.
    const roomVersions = Object.keys(data.room_versions).sort(cmpRoomVersions);
    const defaultRoomVersions = Object.keys(data.default_room_versions).sort(cmpRoomVersions);

    var barDatasets = [];
    var scatterDatasets = [];

    for (let project in data.homeserver_versions) {
        const projectVersions = data.homeserver_versions[project]["lag_" + displayType];

        // If there are no versions, don't bother adding them.
        if (!Object.keys(projectVersions).length) {
            continue;
        }

        barDatasets.push({
            label: project,
            // Fill in zeros for missing spec versions.
            data: specVersions.map(v => projectVersions[v] || 0),
            borderWidth: 1,
        })

        scatterDatasets.push({
            label: project,
            data: Object.keys(projectVersions).map(v => {
                return {
                    label: v,
                    x: data.spec_versions.lag[v],
                    y: projectVersions[v]
                };
            }),
            borderWidth: 1,
        })
    }

    // Bar chart of the number of days between a spec release and the homeserver
    // supporting it.
    const barChart = Chart.getChart("days-to-support");
    barChart.data = {
        labels: specVersions,
        datasets: barDatasets,
    };
    barChart.update();

    // Scatter chart of the number of days between a spec release and the homeserver
    // supporting it.
    const scatterChart = Chart.getChart("spec-days-vs-support");
    scatterChart.data = {
        datasets: scatterDatasets,
    };
    scatterChart.update();

    // Generate timeline date for spec & room versions supporteed.
    const now = new Date();
    const specVersionsDataset = [];
    const roomVersionsDataset = [];
    const defaultRoomVersionsDataset = [];

    for (let project in data.homeserver_versions) {
        addVersionsToDataset(specVersionsDataset, now, project, data.homeserver_versions[project].spec_version_dates);

        for (let [data_key, dataset] of [["room_version_dates", roomVersionsDataset], ["default_room_version_dates", defaultRoomVersionsDataset]]) {
            addVersionsToDataset(dataset, now, project, data.homeserver_versions[project][data_key]);
        }
    }

    // Timeline showing the dates when spec versions were supported.
    const specVersionsSupportedChart = Chart.getChart("supported-spec-versions-over-time");
    specVersionsSupportedChart.data = {
        labels: specVersions,
        datasets: specVersionsDataset
    };
    specVersionsSupportedChart.options.plugins.annotation = {
        annotations: annotationsFromReleaseDates(data.spec_versions.version_dates, rotation=-90)
    }
    specVersionsSupportedChart.update();

    // Timeline showing the dates when room versions were supported.
    const roomVersionsSupportedChart = Chart.getChart("supported-room-versions-over-time");
    roomVersionsSupportedChart.data = {
        labels: roomVersions,
        datasets: roomVersionsDataset
    };
    roomVersionsSupportedChart.options.plugins.annotation = {
        annotations: annotationsFromReleaseDates(data.room_versions, rotation=0)
    }
    roomVersionsSupportedChart.update();

    const defaultRoomVersionsChart = Chart.getChart("default-room-versions-over-time");
    defaultRoomVersionsChart.data = {
        labels: defaultRoomVersions,
        datasets: defaultRoomVersionsDataset
    };
    defaultRoomVersionsChart.options.plugins.annotation = {
        annotations: annotationsFromReleaseDates(data.default_room_versions, rotation=0)
    }
    defaultRoomVersionsChart.update();
}

// Build the initial version.
build();