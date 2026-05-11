from pathlib import Path
import colorsys

import numpy as np
import skrf as rf
import plotly.graph_objects as go


def get_graph_colors(n: int):
    """
    Generate n visually different RGB colors for Plotly traces.
    """
    colors = []

    if n <= 0:
        return colors

    for i in range(n):
        hue = i / n
        lightness = 0.45
        saturation = 0.8

        rgb = colorsys.hls_to_rgb(hue, lightness, saturation)
        rgb_ints = tuple(int(value * 255) for value in rgb)
        colors.append(rgb_ints)

    return colors


def read_sparameter(file_path, parameter: str = "S21", unwrap_phase: bool = True):
    """
    Read one .s2p file and return:
    - frequency in GHz
    - magnitude in dB
    - phase in degrees

    parameter can be: S11, S21, S12, or S22.
    """
    file_path = Path(file_path)

    parameter_map = {
        "S11": (0, 0),
        "S21": (1, 0),
        "S12": (0, 1),
        "S22": (1, 1),
    }

    parameter = parameter.upper()

    if parameter not in parameter_map:
        raise ValueError("parameter must be one of: S11, S21, S12, S22")

    row, col = parameter_map[parameter]

    network = rf.Network(str(file_path))

    frequency_ghz = network.f / 1e9
    s_complex = network.s[:, row, col]

    magnitude = np.abs(s_complex)
    magnitude_db = 10 * np.log10(np.maximum(magnitude, 1e-20))

    phase_rad = np.angle(s_complex)
    if unwrap_phase:
        phase_rad = np.unwrap(phase_rad)

    phase_deg = np.degrees(phase_rad)

    return frequency_ghz, magnitude_db, phase_deg


def get_plot_output_folder(output_root, parameter: str, plot_type: str):
    """
    Create and return output folder:
    plot/S21/magnitude_plots
    plot/S21/phase_plots
    plot/S11/magnitude_plots
    plot/S11/phase_plots
    """
    output_root = Path(output_root)
    parameter = parameter.upper()

    if plot_type not in ("magnitude", "phase"):
        raise ValueError("plot_type must be 'magnitude' or 'phase'")

    folder_name = "magnitude_plots" if plot_type == "magnitude" else "phase_plots"

    final_folder = output_root / parameter / folder_name
    final_folder.mkdir(parents=True, exist_ok=True)

    return final_folder


def make_power_sweep_html(
    input_folder,
    output_root="plot",
    parameter: str = "S21",
    plot_type: str = "magnitude",
    title: str | None = None,
    show: bool = False,
):
    """
    Create one HTML plot for a power sweep.

    Use this when:
    - all .s2p files have the same frequency range
    - each .s2p file corresponds to a different power
    """
    input_folder = Path(input_folder)
    parameter = parameter.upper()
    plot_type = plot_type.lower()

    s2p_files = sorted(input_folder.glob("*.s2p"), key=lambda x: x.name.lower())

    if not s2p_files:
        raise FileNotFoundError(f"No .s2p files found in: {input_folder}")

    colors = get_graph_colors(len(s2p_files))
    fig = go.Figure()

    for index, file_path in enumerate(s2p_files):
        frequency_ghz, magnitude_db, phase_deg = read_sparameter(
            file_path=file_path,
            parameter=parameter,
        )

        if plot_type == "magnitude":
            y_data = magnitude_db
            y_label = f"|{parameter}| (dB)"
        elif plot_type == "phase":
            y_data = phase_deg
            y_label = f"Phase of {parameter} (degrees)"
        else:
            raise ValueError("plot_type must be 'magnitude' or 'phase'")

        fig.add_trace(
            go.Scattergl(
                x=frequency_ghz,
                y=y_data,
                mode="lines",
                name=file_path.stem,
                line=dict(
                    color=f"rgb{colors[index]}",
                    width=1.5,
                ),
                opacity=0.8,
            )
        )

    if title is None:
        title = f"{parameter} power sweep - {plot_type} - {input_folder.name}"

    fig.update_layout(
        height=900,
        title=title,
        template="ggplot2",
        xaxis_title="Frequency (GHz)",
        yaxis_title=y_label,
        legend_title="Power / scan file",
    )

    output_folder = get_plot_output_folder(output_root, parameter, plot_type)
    output_file = output_folder / f"{input_folder.name}_{parameter}_{plot_type}_power_sweep.html"
    fig.write_html(str(output_file))

    if show:
        fig.show()

    return output_file


def make_frequency_sweep_html(
    input_folder,
    output_root="plot",
    parameter: str = "S21",
    plot_type: str = "magnitude",
    title: str | None = None,
    show: bool = False,
):
    """
    Create one HTML plot for a frequency sweep.

    Use this when:
    - each .s2p file is a different frequency segment
    - example: 1-2 GHz, 2-3 GHz, 3-4 GHz, etc.

    Each segment is plotted in a different color.
    Legend is hidden to avoid clutter.
    """
    input_folder = Path(input_folder)
    parameter = parameter.upper()
    plot_type = plot_type.lower()

    s2p_files = sorted(input_folder.glob("*.s2p"), key=lambda x: x.name.lower())

    if not s2p_files:
        raise FileNotFoundError(f"No .s2p files found in: {input_folder}")

    colors = get_graph_colors(len(s2p_files))
    fig = go.Figure()

    for index, file_path in enumerate(s2p_files):
        frequency_ghz, magnitude_db, phase_deg = read_sparameter(
            file_path=file_path,
            parameter=parameter,
        )

        if plot_type == "magnitude":
            y_data = magnitude_db
            y_label = f"|{parameter}| (dB)"
        elif plot_type == "phase":
            y_data = phase_deg
            y_label = f"Phase of {parameter} (degrees)"
        else:
            raise ValueError("plot_type must be 'magnitude' or 'phase'")

        fig.add_trace(
            go.Scattergl(
                x=frequency_ghz,
                y=y_data,
                mode="lines",
                line=dict(
                    color=f"rgb{colors[index]}",
                    width=1.5,
                ),
                opacity=0.9,
                showlegend=False,   # hides legend labels
            )
        )

    if title is None:
        title = f"{parameter} frequency sweep - {plot_type} - {input_folder.name}"

    fig.update_xaxes(title_text="Freq(GHz)", tickformat=".6s",ticksuffix="GHz", row=1, col=1, title_font=dict(size=26), tickfont=dict(size=22))
    fig.update_yaxes(title_text=y_label, row=1, col=1, title_font=dict(size=26), tickfont=dict(size=22))

    fig.update_layout(
        height=900,
        title=title,
        template="ggplot2",
        showlegend=False,
    )

    output_folder = get_plot_output_folder(output_root, parameter, plot_type)
    output_file = output_folder / f"{input_folder.name}_{parameter}_{plot_type}_frequency_sweep.html"
    fig.write_html(str(output_file))

    if show:
        fig.show()

    return output_file


def make_sweep_html(
    input_folder,
    sweep_type: str,
    parameter: str = "S21",
    plot_type: str = "magnitude",
    output_root="plot",
    show: bool = False,
):
    """
    General function.

    sweep_type:
    - "power"
    - "frequency"

    plot_type:
    - "magnitude"
    - "phase"
    """
    sweep_type = sweep_type.lower()

    if sweep_type == "power":
        return make_power_sweep_html(
            input_folder=input_folder,
            output_root=output_root,
            parameter=parameter,
            plot_type=plot_type,
            show=show,
        )

    if sweep_type == "frequency":
        return make_frequency_sweep_html(
            input_folder=input_folder,
            output_root=output_root,
            parameter=parameter,
            plot_type=plot_type,
            show=show,
        )

    raise ValueError("sweep_type must be either 'power' or 'frequency'")


def make_both_plots(
    input_folder,
    sweep_type: str,
    parameter: str = "S21",
    output_root="plot",
    show: bool = False,
):
    """
    Create both magnitude and phase plots.
    """
    magnitude_file = make_sweep_html(
        input_folder=input_folder,
        sweep_type=sweep_type,
        parameter=parameter,
        plot_type="magnitude",
        output_root=output_root,
        show=show,
    )

    phase_file = make_sweep_html(
        input_folder=input_folder,
        sweep_type=sweep_type,
        parameter=parameter,
        plot_type="phase",
        output_root=output_root,
        show=show,
    )

    return magnitude_file, phase_file

def make_all_temperature_folders_html(
    base_folder,
    sweep_type: str,
    parameters=("S21", "S11"),
    output_root="plot",
    show: bool = False,
):
    """
    Process a base folder that contains many temperature folders.

    Example structure:

    base_folder/
    ├── 2026-04-23-09-39-58_3897.92mK/
    │   ├── scan1.s2p
    │   ├── scan2.s2p
    │   └── ...
    ├── 2026-04-23-09-52-46_3681.09mK/
    │   ├── scan1.s2p
    │   ├── scan2.s2p
    │   └── ...
    └── ...

    For each temperature folder, this creates:
    - magnitude plot
    - phase plot

    For each parameter in parameters, for example:
    - S21
    - S11
    """
    base_folder = Path(base_folder)

    temperature_folders = sorted(
        [folder for folder in base_folder.iterdir() if folder.is_dir()],
        key=lambda x: x.name.lower(),
    )

    if not temperature_folders:
        raise FileNotFoundError(f"No temperature folders found in: {base_folder}")

    created_files = []

    for temperature_folder in temperature_folders:
        s2p_files = list(temperature_folder.glob("*.s2p"))

        if not s2p_files:
            print(f"Skipping folder without .s2p files: {temperature_folder}")
            continue

        for parameter in parameters:
            magnitude_file, phase_file = make_both_plots(
                input_folder=temperature_folder,
                sweep_type=sweep_type,
                parameter=parameter,
                output_root=output_root,
                show=show,
            )

            created_files.append(magnitude_file)
            created_files.append(phase_file)

    return created_files