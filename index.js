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

function resetZoom(chartId) {
    Chart.getChart(chartId).resetZoom();
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
            }
        },
        plugins: [ChartDataLabels]
    });

    const versionsSupportedContext = document.getElementById("supported-versions-over-time");
    new Chart(versionsSupportedContext, {
        type: "bar",
        data: null,
        options: {
            indexAxis: "y",
            // Add height since there's so many lines.
            aspectRatio: 1,
            scales: {
                x: {
                    min: "2016-01-01",
                    type: "time",
                },
            },
            plugins: {
                title: {
                    display: true,
                    text: "Supported versions over time",
                },
                zoom: zoomOptions
            }
        },
    });

    // Add the initial data.
    render();
}

function render() {
    let allowedMaturities = ["stable", "beta", "alpha", "obsolete"].filter(maturity => document.getElementById(maturity).checked);
    let displayAllReleases = !document.getElementById("display-all-releases").checked;

    fetch("data.json").then(response => response.json()).then(data => {
        // The full list of released spec versions.
        const specVersions = Object.keys(data.spec_versions.version_dates).sort(cmpVersions);
        
        var barDatasets = [];
        var scatterDatasets = [];

        for (let project in data.homeserver_versions) {
            const projectVersions = data.homeserver_versions[project]["lag_" + (displayAllReleases ? "after_release" : "all")];

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

        // Line showing the dates when versions were supported.
        const now = new Date();
        const versionsDatasets = [];
        for (let project in data.homeserver_versions) {
            const projectVersions = data.homeserver_versions[project].version_dates;

            // If there are no versions, don't bother adding them.
            if (!Object.keys(projectVersions).length) {
                continue;
            }

            // Filter projects by maturity.
            if (!allowedMaturities.includes(data.homeserver_versions[project].maturity)) {
                continue
            }

            versionsDatasets.push(
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

        const versionsSupportedChart = Chart.getChart("supported-versions-over-time");
        versionsSupportedChart.data = {
            labels: specVersions,
            datasets: versionsDatasets
        };
        versionsSupportedChart.update();
    });
}

// Build the initial version.
build();