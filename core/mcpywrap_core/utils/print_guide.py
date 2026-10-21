import click


def print_guide():
    click.echo(click.style("\n⩸⩸⩸⩸ 📋 如何继续？ ⩸⩸⩸⩸\n", fg="bright_cyan"))

    click.echo(click.style("🎮 ", fg="green") +
                click.style("mcpy run", fg="bright_green", bold=True) +
                click.style("    - 启动游戏进行测试", fg="white"))
    
    click.echo(click.style("✏️  ", fg="cyan") + 
               click.style("mcpy edit", fg="bright_cyan", bold=True) + 
               click.style("  - 使用 MC Studio Editor 编辑器进行编辑", fg="white"))
    
    click.echo(click.style("🔄 ", fg="yellow") + 
               click.style("mcpy dev", fg="bright_yellow", bold=True) + 
               click.style("    - 进入实时构建开发模式", fg="white"))
    
    click.echo(click.style("🏗️  ", fg="blue") + 
               click.style("mcpy build", fg="bright_blue", bold=True) + 
               click.style("  - 进行单次构建", fg="white"))
    
    click.echo(click.style("📦 ", fg="magenta") + 
               click.style("mcpy add", fg="bright_magenta", bold=True) + 
               click.style(" <package>", fg="bright_white") + 
               click.style(" - 手动添加依赖包", fg="white"))
    
    
    click.echo("\n")

