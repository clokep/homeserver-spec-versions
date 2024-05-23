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

function buildTimeline(elementId, title, yAxisTitle) {
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
                    min: "2015-10-01",
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
    buildTimeline("supported-spec-versions-over-time", "Supported spec versions over time", "Spec version");
    buildTimeline("supported-room-versions-over-time", "Supported room versions over time", "Room version");
    buildTimeline("default-room-versions-over-time", "Default room versions over time", "Room version");

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
    let allowedMaturities = ["stable", "beta", "alpha", "obsolete"].filter(maturity => document.getElementById(maturity).checked);
    let displayType = document.getElementById("display-type").value;

    fetch("data.json").then(response => response.json()).then(data => {
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

            // Filter projects by maturity.
            if (!allowedMaturities.includes(data.homeserver_versions[project].maturity)) {
                continue
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

        // Timeline showing the dates when spec versions were supported.
        const now = new Date();
        const specVersionsDataset = [];
        for (let project in data.homeserver_versions) {
            const projectVersions = data.homeserver_versions[project].spec_version_dates;

            // If there are no versions, don't bother adding them.
            if (!Object.keys(projectVersions).length) {
                continue;
            }

            // Filter projects by maturity.
            if (!allowedMaturities.includes(data.homeserver_versions[project].maturity)) {
                continue
            }

            specVersionsDataset.push(
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
        const roomVersionsDataset = [];
        const defaultRoomVersionsDataset = [];
        for (let project in data.homeserver_versions) {
            for (let [data_key, results] of [["room_version_dates", roomVersionsDataset], ["default_room_version_dates", defaultRoomVersionsDataset]]) {
                const projectVersions = data.homeserver_versions[project][data_key];

                // If there are no versions, don't bother adding them.
                if (!Object.keys(projectVersions).length) {
                    continue;
                }

                // Filter projects by maturity.
                if (!allowedMaturities.includes(data.homeserver_versions[project].maturity)) {
                    continue
                }

                results.push(
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
        }

        const roomVersionsSupportedChart = Chart.getChart("supported-room-versions-over-time");
        roomVersionsSupportedChart.data = {
            // Add a dummy entry for room for the line labels.
            labels: roomVersions,
            datasets: roomVersionsDataset
        };
        roomVersionsSupportedChart.options.plugins.annotation = {
            annotations: annotationsFromReleaseDates(data.room_versions, rotation=0)
        }
        roomVersionsSupportedChart.update();

        const defaultRoomVersionsChart = Chart.getChart("default-room-versions-over-time");
        defaultRoomVersionsChart.data = {
            // Add a dummy entry for room for the line labels.
            labels: defaultRoomVersions,
            datasets: defaultRoomVersionsDataset
        };
        defaultRoomVersionsChart.options.plugins.annotation = {
            annotations: annotationsFromReleaseDates(data.default_room_versions, rotation=0)
        }
        defaultRoomVersionsChart.update();
    });
}

// Build the initial version.
build();