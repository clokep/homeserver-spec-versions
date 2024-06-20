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

    // Timeline of homeserver history.
    const historyContext = document.getElementById("homeserver-history");
    new Chart(historyContext, {
        type: "line",
        data: null,
        options: {
            plugins: {
                title: {
                    display: true,
                    text: "Homeserver History",
                },
                zoom: zoomOptions,
            },
            scales: {
                x: {
                    min: "2014-08-01",
                    title: {
                        display: true,
                        text: "Date"
                    },
                    type: "time"
                }
            }
        }
    });

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

    // Timeline showing the dates when spec versions were supported.
    const now = new Date();
    const specVersionsDataset = [];
    for (let project in data.homeserver_versions) {
        const projectVersions = data.homeserver_versions[project].spec_version_dates;

        // If there are no versions, don't bother adding them.
        if (!Object.keys(projectVersions).length) {
            continue;
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

    // Create data for family tree diagram.
    const homeserverHistoryDataset = [];
    // Group homeservers by family.
    const projectsByFamily = Object.entries(data.homeserver_versions).sort(([a_name, a], [b_name, b]) => {
        // Use the project's date by default.
        let a_date = a.initial_commit_date;
        let b_date = b.initial_commit_date;

        // If the homeservers are of different families, use the origin project's date.
        if ((a.forked_from || a_name) !== (b.forked_from || b_name)) {
            a_date = a.forked_from ? data.homeserver_versions[a.forked_from].initial_commit_date : a.initial_commit_date;
            b_date = b.forked_from ? data.homeserver_versions[b.forked_from].initial_commit_date : b.initial_commit_date;
        }

        return new Date(a_date) - new Date(b_date);
    });
    for (let idx in projectsByFamily) {
        // If
        const [project, projectInfo] = projectsByFamily[idx];
        let data = [
            {
                x: projectInfo.initial_commit_date,
                y: idx
            },
            {
                x: projectInfo.last_commit_date,
                y: idx
            }
        ];

        if (projectInfo.forked_from) {
            data.unshift({
                x: projectInfo.forked_date,
                y: projectsByFamily.findIndex(
                  ([p, pInfo]) => p === projectInfo.forked_from)
            });
        }

        homeserverHistoryDataset.push(
          {
              label: project,
              data: data
          }
        )
    }

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

    const homeserverHistoryChart = Chart.getChart("homeserver-history");
    homeserverHistoryChart.data = {
        datasets: homeserverHistoryDataset
    };
    homeserverHistoryChart.update();
}

// Build the initial version.
build();