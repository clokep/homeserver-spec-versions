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

function build() {
    // Timeline of homeserver history.
    const historyContext = document.getElementById("homeserver-history");
    new Chart(historyContext, {
        type: "line",
        data: null,
        options: {
            // Add height since there's so many lines.
            aspectRatio: 1,
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
                },
                y: {
                    // The y-axis doesn't mean anything, it just groups families.
                    display: false,
                    // Put the oldest family on top.
                    reverse: true
                }
            }
        }
    });

    // Add the initial data.
    render();
}


function render() {
    let allowedMaturities = ["stable", "beta", "alpha", "obsolete", "unstarted"].filter(maturity => document.getElementById(maturity).checked);

    fetch("data.json").then(response => response.json()).then(data => {
        // Filter the displayed projects by maturity.
        data.homeserver_versions = Object.fromEntries(
            Object.entries(data.homeserver_versions).filter(
                ([project, projectInfo]) => allowedMaturities.includes(projectInfo.maturity)
            )
        );

        renderData(data);
    });
}

/**
 * Render the data which has already been filtered for ignored homeservers.
 */
function renderData(data) {
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

    console.log(projectsByFamily)

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

    const homeserverHistoryChart = Chart.getChart("homeserver-history");
    homeserverHistoryChart.data = {
        datasets: homeserverHistoryDataset
    };
    homeserverHistoryChart.update();
}

// Build the initial version.
build();