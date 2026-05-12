def power_and_verify(base: int, exponent: int, expected: int) -> None:
    """计算幂运算并验证结果。"""
    result = base ** exponent
    assert result == expected, f'{base}**{exponent} 期望 {expected}, 实际 {result}'
    print(f'{base} ** {exponent} = {result}, 验证通过 ✓')

if __name__ == '__main__':
    power_and_verify(base=2, exponent=10, expected=1024)
